"""Sprint-1 backend: alert ingestion contract + camera registry.

Run locally:
    cd graduation-project/backend
    uvicorn app.main:app --reload --port 8000

Docs: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import repository as repo
from .config import Settings
from .db import connect, init_db, utc_now
from .errors import ApiError, error_body
from .schemas import (
    AlertAccepted,
    AlertCreate,
    AlertOut,
    AlertPage,
    AlertStatusUpdate,
    CameraCreate,
    CameraOut,
    EventType,
)

logger = logging.getLogger("alerts.api")

SERVICE_VERSION = "0.1.0-sprint1"


def get_conn(request: Request):
    conn = connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def require_ingest_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """Shared-secret guard for the ingestion path.

    Disabled (open) when INGEST_API_KEY is unset, which is the local default.
    JWT + RBAC replaces this in Sprint 2.
    """
    expected = request.app.state.settings.ingest_api_key
    if not expected:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise ApiError(
            status_code=401,
            code="invalid_api_key",
            message="Missing or invalid X-API-Key header.",
        )


def build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(settings.db_path, settings.seed_demo_cameras)
        logger.info("alerts API ready (db=%s)", settings.db_path)
        yield

    app = FastAPI(
        title="Smart College Surveillance - Alerts API",
        version=SERVICE_VERSION,
        description=(
            "Sprint 1 slice of the cloud surveillance platform: one camera registry "
            "and one alert ingestion endpoint, decoupled from the AI models."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Strip the auto-generated 422 validation responses from OpenAPI; we use 400 instead.
    _orig_openapi = app.openapi

    def _custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        for path_item in openapi_schema.get("paths", {}).values():
            for operation in path_item.values():
                if isinstance(operation, dict):
                    operation.get("responses", {}).pop("422", None)
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = _custom_openapi

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------ errors
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in error["loc"][1:]) or "body",
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=400,
            content=error_body(
                "validation_error", "Request validation failed.", details
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=error_body("internal_error", "Unexpected server error."),
        )

    # ----------------------------------------------------------------- routes
    @app.get("/", tags=["meta"], summary="Service banner")
    def root() -> dict[str, Any]:
        return {
            "service": "alerts-api",
            "version": SERVICE_VERSION,
            "docs": "/docs",
            "endpoints": [
                "POST /api/v1/alerts",
                "GET /api/v1/alerts",
                "GET /api/v1/alerts/{event_id}",
                "PATCH /api/v1/alerts/{event_id}/status",
                "GET /api/v1/cameras",
                "POST /api/v1/cameras",
                "GET /health",
            ],
        }

    @app.get("/health", tags=["meta"], summary="Liveness and DB check")
    def health() -> dict[str, str]:
        conn = connect(settings.db_path)
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        return {"status": "ok", "database": "ok", "version": SERVICE_VERSION}

    @app.post(
        "/api/v1/alerts",
        tags=["alerts"],
        status_code=201,
        response_model=AlertAccepted,
        dependencies=[Depends(require_ingest_key)],
        summary="Ingest one alert from an AI service or the health monitor",
        responses={
            200: {"description": "Duplicate event_id, already stored (idempotent)."},
            400: {"description": "Validation failed (missing or invalid fields)."},
            401: {"description": "Missing or invalid X-API-Key."},
        },
    )
    def create_alert(
        payload: AlertCreate,
        response: Response,
        conn=Depends(get_conn),
    ) -> AlertAccepted:
        received_at = utc_now()
        try:
            created = repo.insert_alert(conn, payload, received_at)
        except repo.UnknownCamera:
            raise ApiError(
                status_code=400,
                code="unknown_camera",
                message=(
                    f"Camera '{payload.camera_id}' is not registered or is disabled. "
                    "Register it with POST /api/v1/cameras first."
                ),
                details={"camera_id": payload.camera_id},
            )

        if created:
            response.status_code = 201
            return AlertAccepted(
                event_id=payload.event_id,
                status="new",
                duplicate=False,
                received_at=received_at,
            )

        existing = repo.get_alert(conn, str(payload.event_id))
        assert existing is not None  # the row exists, it caused the conflict
        response.status_code = 200
        return AlertAccepted(
            event_id=payload.event_id,
            status=existing["status"],
            duplicate=True,
            received_at=existing["received_at"],
        )

    @app.get(
        "/api/v1/alerts",
        tags=["alerts"],
        response_model=AlertPage,
        summary="List / filter alerts (newest first)",
    )
    def list_alerts(
        conn=Depends(get_conn),
        status: str | None = Query(None, pattern="^(new|confirmed|dismissed)$"),
        event_type: EventType | None = None,
        camera_id: str | None = None,
        global_id: str | None = None,
        since: AwareDatetime | None = Query(None, alias="from"),
        until: AwareDatetime | None = Query(None, alias="to"),
        min_confidence: float | None = Query(None, ge=0, le=1),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> AlertPage:
        items, total = repo.list_alerts(
            conn,
            status=status,
            event_type=event_type,
            camera_id=camera_id,
            global_id=global_id,
            since=since,
            until=until,
            min_confidence=min_confidence,
            limit=limit,
            offset=offset,
        )
        return AlertPage(
            items=[AlertOut(**item) for item in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    @app.get(
        "/api/v1/alerts/{event_id}",
        tags=["alerts"],
        response_model=AlertOut,
        summary="Read one alert",
    )
    def read_alert(event_id: str, conn=Depends(get_conn)) -> AlertOut:
        alert = repo.get_alert(conn, event_id)
        if alert is None:
            raise ApiError(404, "alert_not_found", f"No alert with event_id {event_id}.")
        return AlertOut(**alert)

    @app.patch(
        "/api/v1/alerts/{event_id}/status",
        tags=["alerts"],
        response_model=AlertOut,
        summary="Operator decision: confirm or dismiss",
        responses={409: {"description": "Alert is already in a final state."}},
    )
    def update_status(
        event_id: str,
        payload: AlertStatusUpdate,
        conn=Depends(get_conn),
        x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    ) -> AlertOut:
        try:
            alert = repo.update_alert_status(
                conn,
                event_id=event_id,
                new_status=payload.status,
                actor=x_user_id,
                note=payload.note,
                changed_at=utc_now(),
            )
        except repo.AlertNotFound:
            raise ApiError(404, "alert_not_found", f"No alert with event_id {event_id}.")
        except repo.InvalidTransition as exc:
            raise ApiError(
                409,
                "invalid_status_transition",
                f"Alert is already '{exc.current}'; only 'new' alerts can be decided.",
                {"current": exc.current, "requested": exc.requested},
            )
        return AlertOut(**alert)

    @app.get(
        "/api/v1/cameras",
        tags=["cameras"],
        response_model=list[CameraOut],
        summary="List registered cameras",
    )
    def list_cameras(conn=Depends(get_conn)) -> list[CameraOut]:
        return [CameraOut(**camera) for camera in repo.list_cameras(conn)]

    @app.post(
        "/api/v1/cameras",
        tags=["cameras"],
        status_code=201,
        response_model=CameraOut,
        summary="Register a camera (demo helper, admin UI comes later)",
        responses={409: {"description": "camera_id already registered."}},
    )
    def register_camera(
        payload: CameraCreate,
        response: Response,
        conn=Depends(get_conn),
    ) -> CameraOut:
        try:
            camera = repo.create_camera(conn, payload, utc_now())
        except repo.CameraAlreadyExists:
            raise ApiError(
                409,
                "camera_already_exists",
                f"Camera {payload.camera_id} is already registered.",
            )
        response.status_code = 201
        return CameraOut(**camera)

    return app


app = build_app()
