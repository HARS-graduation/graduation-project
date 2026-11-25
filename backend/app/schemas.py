"""Request/response models. These are the executable version of the API contract.

Field names match the agreed event contract exactly (see docs/api-contract.md).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

EventType = Literal[
    "fight",
    "smoking",
    "camera_disconnected",
    "camera_frozen",
    "person_handoff",
]

AlertStatus = Literal["new", "confirmed", "dismissed"]

CameraStatus = Literal["online", "offline", "frozen", "unknown"]

# AI services may miss the clock by a small amount; anything further ahead is a bug.
MAX_CLOCK_SKEW = timedelta(minutes=5)


class AlertCreate(BaseModel):
    """Payload posted by an AI service or the health monitor."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(
        description="Client-generated UUIDv4/v7. Used as an idempotency key."
    )
    event_type: EventType
    camera_id: str = Field(min_length=1, max_length=64)
    timestamp: AwareDatetime = Field(
        description="When the event happened, ISO-8601 with offset (UTC preferred)."
    )
    confidence: float = Field(ge=0.0, le=1.0)
    track_id: str | None = Field(default=None, max_length=64)
    global_id: str | None = Field(default=None, max_length=64)
    clip_uri: str | None = Field(default=None, max_length=1024)
    snapshot_uri: str | None = Field(default=None, max_length=1024)
    reason: str | None = Field(default=None, max_length=500)
    status: AlertStatus = Field(
        default="new",
        description="Only 'new' is accepted on creation; operators change it later.",
    )

    @field_validator("timestamp")
    @classmethod
    def _normalise_timestamp(cls, value: datetime) -> datetime:
        value = value.astimezone(timezone.utc)
        if value > datetime.now(timezone.utc) + MAX_CLOCK_SKEW:
            raise ValueError("timestamp is more than 5 minutes in the future")
        return value

    @field_validator("status")
    @classmethod
    def _only_new_is_creatable(cls, value: str) -> str:
        if value != "new":
            raise ValueError("a new alert must be created with status 'new'")
        return value

    @field_validator("camera_id")
    @classmethod
    def _strip_camera_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("camera_id cannot be empty or whitespace")
        return stripped

    @field_validator(
        "track_id", "global_id", "clip_uri", "snapshot_uri", "reason", mode="before"
    )
    @classmethod
    def _strip_optional_strings(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else None
        return value


class AlertStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["confirmed", "dismissed"]
    note: str | None = Field(default=None, max_length=500)


class AlertAccepted(BaseModel):
    event_id: UUID
    status: AlertStatus
    duplicate: bool = Field(
        description="True when this event_id had already been stored; the request was ignored."
    )
    received_at: datetime


class AlertOut(BaseModel):
    event_id: UUID
    event_type: EventType
    camera_id: str
    camera_name: str | None = None
    zone: str | None = None
    timestamp: datetime
    confidence: float
    track_id: str | None = None
    global_id: str | None = None
    clip_uri: str | None = None
    snapshot_uri: str | None = None
    reason: str | None = None
    status: AlertStatus
    status_by: str | None = None
    status_at: datetime | None = None
    received_at: datetime


class AlertPage(BaseModel):
    items: list[AlertOut]
    total: int
    limit: int
    offset: int


class CameraCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    zone: str = Field(min_length=1, max_length=120)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    stream_path: str = Field(min_length=1, max_length=120)
    fps_target: float = Field(default=25.0, gt=0, le=120)
    is_active: bool = True

    @field_validator("camera_id", "name", "zone", "stream_path", mode="before")
    @classmethod
    def _strip_required_strings(cls, value):
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("cannot be empty or whitespace")
            return stripped
        return value


class CameraOut(BaseModel):
    camera_id: str
    name: str
    zone: str
    latitude: float
    longitude: float
    stream_path: str
    fps_target: float
    status: CameraStatus
    is_active: bool
    last_seen_at: datetime | None = None
    created_at: datetime
