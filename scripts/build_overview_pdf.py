# -*- coding: utf-8 -*-
"""Build docs/deliverables/design-overview.pdf - a one-file summary of the
Sprint-1 database design package.

    python scripts/build_overview_pdf.py
"""
from __future__ import annotations

import arabic_reshaper
from bidi.algorithm import get_display
from fpdf import FPDF
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "deliverables" / "design-overview.pdf"
ER_PNG = ROOT / "docs" / "diagrams" / "er-core.png"

NAVY = (15, 40, 80)
TEAL = (0, 128, 128)
GREY = (90, 90, 90)
LIGHT = (235, 240, 248)
DARK = (30, 30, 30)
AMBER = (180, 120, 0)


def ar(s: str) -> str:
    if not s:
        return s
    return get_display(arabic_reshaper.reshape(s))


class PDF(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=16)
        self.add_font("T", "", r"C:\Windows\Fonts\tahoma.ttf")
        self.add_font("TB", "", r"C:\Windows\Fonts\tahomabd.ttf")
        self.set_font("T", size=10.5)

    def footer(self):
        self.set_y(-12)
        self.set_font("T", size=8)
        self.set_text_color(*GREY)
        self.cell(0, 6, ar(f"ملخص التصميم - منصة المراقبة الذكية | صفحة {self.page_no()}"),
                  align="C")
        self.set_text_color(*DARK)

    def ensure_new_page(self):
        if self.get_y() > self.t_margin + 5:
            self.add_page()

    def rtl(self, text, size=10.5, bold=False, color=DARK, align="R", space=4):
        self.set_font("TB" if bold else "T", size=size)
        self.set_text_color(*color)
        self.multi_cell(0, 5.2, ar(text), align=align, new_x="LMARGIN", new_y="NEXT")
        self.ln(space - 4 if space > 4 else 0)
        self.set_text_color(*DARK)

    def ltr(self, text, size=9.5, color=(40, 40, 40), space=2):
        self.set_font("T", size=size)
        self.set_text_color(*color)
        self.multi_cell(0, 4.6, ar(text), align="L", new_x="LMARGIN", new_y="NEXT")
        self.ln(space)
        self.set_text_color(*DARK)

    def heading(self, text, size=13, color=NAVY, space=3):
        self.set_font("TB", size=size)
        self.set_text_color(*color)
        self.multi_cell(0, 6.5, ar(text), align="R", new_x="LMARGIN", new_y="NEXT")
        y = self.get_y()
        self.set_draw_color(*TEAL)
        self.set_line_width(0.4)
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.ln(space)
        self.set_text_color(*DARK)

    def sub(self, text, size=11, color=TEAL, space=2):
        self.set_font("TB", size=size)
        self.set_text_color(*color)
        self.multi_cell(0, 5.5, ar(text), align="R", new_x="LMARGIN", new_y="NEXT")
        self.ln(space)
        self.set_text_color(*DARK)

    def bullet(self, text, size=10.5, indent=6, color=DARK, mark="•"):
        self.set_font("T", size=size)
        self.set_text_color(*color)
        self.multi_cell(0, 5.2, ar(f"{mark}  {text}"), align="R",
                        new_x="LMARGIN", new_y="NEXT")
        self.ln(0.5)

    def kv(self, key, value, key_color=TEAL):
        self.set_font("TB", size=10)
        self.set_text_color(*key_color)
        self.write(5.2, ar(key) + "  ")
        self.set_font("T", size=10)
        self.set_text_color(*DARK)
        self.multi_cell(0, 5.2, ar(value), align="R", new_x="LMARGIN", new_y="NEXT")
        self.ln(0.3)

    def box(self, title, lines, fill=LIGHT, title_color=NAVY):
        self.set_fill_color(*fill)
        self.set_font("TB", size=10.5)
        self.set_text_color(*title_color)
        self.cell(0, 6, ar(title), align="R", new_x="LMARGIN", new_y="NEXT", fill=True)
        self.set_font("T", size=10)
        self.set_text_color(*DARK)
        for ln in lines:
            self.multi_cell(0, 5, ar(ln), align="R", new_x="LMARGIN",
                            new_y="NEXT", fill=True)
        self.ln(2)

    def header_band(self, title, subtitle=None):
        self.set_fill_color(*NAVY)
        self.rect(0, 0, self.w, 22, "F")
        self.set_xy(self.l_margin, 6)
        self.set_font("TB", size=15)
        self.set_text_color(255, 255, 255)
        self.cell(0, 7, ar(title), align="R", new_x="LMARGIN", new_y="NEXT")
        if subtitle:
            self.set_x(self.l_margin)
            self.set_font("T", size=9.5)
            self.set_text_color(200, 220, 240)
            self.cell(0, 5, ar(subtitle), align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(*DARK)
        self.set_y(26)


FILES = [
    {
        "path": "db/schema.postgres.sql",
        "title": "الـ Schema الأساسي (7 جداول)",
        "purpose": "المصدر الوحيد القابل للتنفيذ على PostgreSQL. هو \"الحقيقة\" (source of truth): "
                   "إذا حصل خلاف بينه وبين أي ملف آخر، هو الصحيح.",
        "contents": [
            "0. Enumerations: event_type, alert_status, camera_status, user_role",
            "1. sites - الكلية (multi-site ready)",
            "2. users - operator / college_admin / system_admin + RBAC",
            "3. cameras - registry + map (PostGIS) + MediaMTX path + health",
            "4. camera_links - الـ camera graph: transit_seconds +/- tolerance",
            "5. alerts - جدول الأحداث (idempotency key = event_id)",
            "6. alert_actions - audit trail + ML labels (append-only)",
            "7. camera_health_events - timeline of status changes",
            "8. Triggers: updated_at (3 جداول) + cameras.geom من lat/lon",
            "9. Write paths: set_camera_status() و decide_alert()",
            "10. Views: camera_edges و alert_feed",
        ],
        "important": [
            "يُنفَّذ كله داخل BEGIN...COMMIT (atomic).",
            "Idempotent: IF NOT EXISTS + حماية enums + إعادة إنشاء triggers.",
            "القيود (CHECK, FK, UNIQUE) في الداتابيز وليس في الـ API فحسب.",
            "NOT a migration tool: تغيير عمود موجود يحتاج Alembic (Sprint 2).",
            "لا بيانات فيه - البيانات في seed.sql.",
        ],
        "usage": "psql -d surveillance -v ON_ERROR_STOP=1 -f db/schema.postgres.sql",
    },
    {
        "path": "db/schema.phase2.postgres.sql",
        "title": "الـ Schema (Phase 2 - 5 جداول إضافية)",
        "purpose": "مصمّم الآن، يُنفَّذ عندما تهبط الميزة. يثبت أن التصميم الأساسي "
                   "لن يكسر (additive) - لا تغيير على الـ 7 جداول.",
        "contents": [
            "1. recording_segments - index للـ Lakehouse (replay by camera/time)",
            "2. tracked_persons - Global ID (مجهول، من غير وجوه)",
            "3. person_tracks - ByteTrack + match_score + timing_delta (I-1 قابلة للقياس)",
            "4. site_settings - retention + face_blur (مسؤولية college admin)",
            "5. audit_log - login/admin audit (مش قرارات الـ alerts)",
        ],
        "important": [
            "يُنفَّذ بعد schema.postgres.sql (FK على cameras, users, sites).",
            "recording_segments: partition by month only when > 10M rows.",
            "tracked_persons يخزن opaque GID فقط - لا صور ولا biometrics.",
        ],
        "usage": "psql -d surveillance -v ON_ERROR_STOP=1 -f db/schema.phase2.postgres.sql",
    },
    {
        "path": "db/seed.sql",
        "title": "بيانات تجريبية (idempotent)",
        "purpose": "الدليل العملي أن التصميم قابل للاستخدام: موقع + 4 كاميرات + "
                   "الـ graph + أوبريتور + alert + action. من غيره الـ Schema فارغ.",
        "contents": [
            "1. sites: BUC-MAIN (Africa/Cairo)",
            "2. users: أوبريتور تجريبي (hash = DISABLED-NO-LOGIN -> لا login)",
            "3. cameras: CAM-001..004 (بوابة، كوريدور، معامل، باركينج)",
            "4. camera_links: 3 وصلات (10s+/-3s, 30s+/-8s, 45s+/-10s)",
            "5. alerts: 1 fight على CAM-002 (يطابق api/samples/create_alert_fight.json)",
            "6. alert_actions: 'created' (actor = NULL)",
        ],
        "important": [
            "كل الإدخالات idempotent (ON CONFLICT / WHERE NOT EXISTS).",
            "الترتيب إجباري: موقع -> users -> cameras -> links -> alerts.",
            "الأوبريتور التجريبي بيتستبدل بـ bootstrap admin (Sprint 2).",
            "اختفى مرة (OneDrive sync) - therefore commit to git.",
        ],
        "usage": "psql -d surveillance -v ON_ERROR_STOP=1 -f db/seed.sql",
    },
    {
        "path": "db/schema.dbml",
        "title": "نموذج مرئي (dbdiagram.io)",
        "purpose": "مرآة الـ SQL بشكل تقدر تلصقه في dbdiagram.io وتستخرج رسم تفاعلي. "
                   "لا يُنفَّذ - فقط للتصور.",
        "contents": [
            "7 Tables + 4 Enums + 9 Refs (cardinalities)",
            "Indexes as comments",
            "Notes on every column",
        ],
        "important": [
            "يجب أن يُحدَّث مع schema.postgres.sql (لا code-gen بينهما).",
            "مصدر render_er.py (توليد PNG/SVG).",
            "الـ enums مرئية هنا (مش في الرسم المُولَّد - لتقليل التشابك).",
        ],
        "usage": "npx @softwaretechnik/dbml-renderer -i db/schema.dbml -f svg",
    },
    {
        "path": "docs/database-design.md",
        "title": "الوثيقة الأم (19 قسم)",
        "purpose": "الـ WHY + قاموس البيانات. كل \"ليه كذا؟\" إجابته هنا. 609 سطر.",
        "contents": [
            "1. ما هي الوثيقة + حالة التحقق",
            "2. Requirements trace (كل متطلب PDF -> أين في Schema)",
            "3. 7 مبادئ التصميم",
            "4. Conceptual model + 4.1 أين الداتابيز في السيستم",
            "5. ER + cardinalities + ON DELETE rules",
            "6. Enumerations",
            "7. Data dictionary (كل عمود)",
            "8. 14 integrity rules",
            "9. Write paths (decide_alert, set_camera_status, ingestion)",
            "10. Alert lifecycle (state machine)",
            "11. Access patterns + indexes (11 queries)",
            "12. Capacity & growth (أرقام + قرار partitioning)",
            "13. Security, privacy, retention",
            "14. Phase-2 tables",
            "15. 13 decisions + rejected alternatives",
            "16. Impact on Sprint-1 API",
            "17. 7 open questions",
            "18. Review checklist",
            "19. File map",
        ],
        "important": [
            "قسم 15 = إجابات \"ليه؟\" (للدكتور).",
            "قسم 7 = قاموس كل عمود.",
            "قسم 11 = لماذا لا index على event_type.",
            "قسم 12 = thresholds (متى ن reconsider partitioning).",
        ],
        "usage": "اقرأها بالترتيب: 1 -> 5 -> 7 -> 15 -> 17.",
    },
    {
        "path": "docs/er-diagram.md",
        "title": "صفحة واحدة مرئية",
        "purpose": "للعرض في التقرير/العرض. ER + cardinalities + enums + views + regenerate.",
        "contents": [
            "صورة ER (PNG/SVG)",
            "معنى كل جدول بسطر",
            "Cardinalities كنص",
            "الـ enums (غير مرسومة لتجنب التشابك)",
            "الـ views (camera_edges, alert_feed)",
            "Phase-2 tables",
            "أمر إعادة التوليد",
        ],
        "important": [
            "Vector (SVG) أفضل للطباعة في Word (لا بكسلة).",
            "الـ enums في جدول (ليس في الرسم).",
        ],
        "usage": "أرفق er-core.svg (ليس PNG) في Word/PowerPoint.",
    },
    {
        "path": "docs/diagrams/er-core.png / .svg",
        "title": "الرسم (مُولَّد آليًا)",
        "purpose": "ER diagram من 7 جداول + علاقات. SVG = 63KB، PNG = 267KB.",
        "contents": [
            "7 tables, 9 foreign keys, cardinalities",
            "Generated from db/schema.dbml via dbml-renderer + Kroki",
        ],
        "important": [
            "لا تعدّل يدويًا - عدّل DBML ثم render_er.py.",
            "SVG stays sharp when scaled (use in slides).",
        ],
        "usage": "python scripts/render_er.py",
    },
    {
        "path": "docs/team-agreement.md",
        "title": "اتفاق الفريق (108 سطر)",
        "purpose": "المهمة الأولى: اتفاق على الحد الأدنى للحقول. 10 قرارات + توقيعات + 5 أسئلة.",
        "contents": [
            "10 decisions (D1-D10) بنعم/لأ + سبب",
            "الحد الأدنى JSON لأي producer",
            "من يرسل ماذا (fight, smoking, tracker, health monitor)",
            "6 قواعد للـ producers (retry, UTC, debounce...)",
            "Mapping: API field <-> DB column",
            "عملية التغيير (من يوافق، versioning)",
            "جدول توقيع فاضي",
            "5 أسئلة مفتوحة",
        ],
        "important": [
            "مش مكتمل بدون توقيعات الفريق.",
            "الـ 5 أسئلة (Q1-Q5) مفتوحة.",
        ],
        "usage": "راجع + وقّع في Sprint review.",
    },
    {
        "path": "docs/api-contract.md",
        "title": "عقد الـ API (330 سطر)",
        "purpose": "الحدود بين الداتابيز والعالم. كل حقل في العقد = عمود في alerts.",
        "contents": [
            "الاتفاقيات (UTC, confidence 0..1, snake_case, idempotency)",
            "المصادقة (X-API-Key -> JWT)",
            "شكل الأخطاء الموحّد + أكواد",
            "POST /alerts (كل حقل + أمثلة 201/200/422/401)",
            "GET /alerts (فلاتر + pagination)",
            "PATCH /alerts/{id}/status (قرار الأوبريتور)",
            "Cameras endpoints",
            "curl examples",
            "\"مش في Sprint 1\" (JWT, WS, clip upload...)",
        ],
        "important": [
            "decide_alert() يُستدعى (لا UPDATE مباشر).",
            "X-User-Id مؤقت -> JWT subject (Sprint 2).",
            "site_id يُضبط من الخادم (default BUC-MAIN).",
        ],
        "usage": "AI team + frontend يبدأون ضده فورًا.",
    },
    {
        "path": "docs/sprint1-report.md",
        "title": "ملخص التسليم (235 سطر)",
        "purpose": "ملف التسليم للدكتور: هدف + deliverables + تحقق + decisions + limitations + خطة.",
        "contents": [
            "1. هدف Sprint",
            "2. جدول التسليمات (6 بنود)",
            "3. ما تم (contract, DB, endpoint)",
            "4. Verification (21 + 17)",
            "5. Top 8 decisions",
            "6. Limitations (6 بنود صريحة)",
            "7. خطة Sprint الجاي (8 tasks)",
            "8. Files",
        ],
        "important": [
            "الـ spike (backend/) معلّم صراحة كـ parked.",
            "Limitations صريحة (PostGIS, auth, replay...).",
        ],
        "usage": "سلّمه للدكتور (28 Oct).",
    },
    {
        "path": "scripts/validate_schema.py",
        "title": "إثبات (21 فحص)",
        "purpose": "يشغّل PostgreSQL 16 حقيقي (pgserver) ويُطبّق Schema + seed + phase2 + 21 assertions.",
        "contents": [
            "Applying core schema / seed / phase-2",
            "Tables exist (7 + 5)",
            "camera_edges = 6 rows (3 links x2)",
            "alert_feed join",
            "Duplicate event_id rejected",
            "Confidence out of range rejected",
            "Decided alert without actor rejected",
            "Future timestamp rejected",
            "decide_alert(): sets + audit row + second rejected + unknown + no actor",
            "set_camera_status(): change + no-op + recovery + unknown",
            "Phase-2 GID + track association",
            "site_settings defaults + trigger",
            "All 6 dashboard indexes exist",
        ],
        "important": [
            "PostGIS NOT bundled -> geom/trigger syntax review only.",
            "Exit code 0 = كل شيء نجح.",
            "لا يغطي: PostGIS, DB roles, API.",
        ],
        "usage": "python scripts/validate_schema.py  -> '21 checks passed.'",
    },
    {
        "path": "scripts/render_er.py",
        "title": "مولد الرسم",
        "purpose": "يقرأ DBML -> DOT -> Kroki (Graphviz) -> SVG + PNG (font metrics consistent).",
        "contents": [
            "Remove Enum blocks (للقراءة)",
            "dbml-renderer -> DOT",
            "Font/size adjustments",
            "Kroki POST (curl, UA Mozilla)",
            "Fallback: local SVG if offline",
        ],
        "important": [
            "يُستخدم curl (python urllib got 403).",
            "لا تُعدّل الصور يدويًا.",
        ],
        "usage": "python scripts/render_er.py",
    },
    {
        "path": "README.md",
        "title": "الفهرس",
        "purpose": "أول ملف يُفتح: حالة المشروع (تصميم)، جدول deliverables، ملخص، ترتيب القراءة، أوامر، خريطة.",
        "contents": [
            "Deliverables table",
            "Design in one screen (7 tables)",
            "Key properties (7 bullets)",
            "Read order (4 steps)",
            "Validate / regenerate commands",
            "Parked API spike note",
            "Layout tree",
            "Scope boundaries",
        ],
        "important": [
            "يقول صراحة: backend/ = parked spike.",
            "No AI/MediaMTX/MinIO/dashboard في هذا Sprint.",
        ],
        "usage": "نقطة الدخول (entry point).",
    },
    {
        "path": "backend/ (parked spike)",
        "title": "FastAPI + SQLite (متوقف)",
        "purpose": "شريحة عملت قبل التصميم (17 tests). مفيدة كـ evidence للـ ingestion contract، "
                   "ليس التنفيذ النهائي.",
        "contents": [
            "app/main.py (endpoints)",
            "app/schemas.py, repository.py, db.py, errors.py, config.py",
            "tests/test_alerts_api.py (17)",
        ],
        "important": [
            "SQLite -> ليس production store.",
            "Predates sites, write functions, stricter rules.",
            "سيُعاد بناؤه على PostgreSQL (Sprint 2).",
            "الـ JSON contract هو الجزء الذي يبقى.",
        ],
        "usage": "uvicorn app.main:app --reload ; pytest (17 passed).",
    },
    {
        "path": "api/ (samples + openapi)",
        "title": "أمثلة JSON",
        "purpose": "Request/response samples + OpenAPI export للـ spike. مرجع للـ AI/frontend.",
        "contents": [
            "create_alert_fight.json (+ smoking, frozen, handoff)",
            "response_201_created, response_200_duplicate",
            "response_400_unknown_camera, response_400_validation_error",
            "response_alert_confirmed",
            "openapi.json (25.7 KB)",
        ],
        "important": [
            "يجب أن ي remain consistent مع api-contract.md.",
            "event_id في fight sample = seed.sql alert.",
        ],
        "usage": "curl -X POST ... -d @api/samples/create_alert_fight.json",
    },
    {
        "path": "requirements-dev.txt",
        "title": "Dev dependencies",
        "purpose": "pgserver + psycopg2-binary (للـ validator). ليس لتشغيل الـ API.",
        "contents": ["pgserver>=0.1.4", "psycopg2-binary>=2.9"],
        "important": ["لا needed لتشغيل الـ API (الـ spike يستخدم SQLite)."],
        "usage": "pip install -r requirements-dev.txt",
    },
]


def build():
    pdf = PDF()
    pdf.set_title("Database Design Overview")
    pdf.set_author("Mohamed Gehad Abdelmonem")
    pdf.set_subject("Smart College Surveillance - Sprint 1")

    # ---------- Title page ----------
    pdf.add_page()
    pdf.set_fill_color(*NAVY)
    pdf.rect(0, 0, pdf.w, 60, "F")
    pdf.set_xy(pdf.l_margin, 18)
    pdf.set_font("TB", size=20)
    pdf.set_text_color(255, 255, 255)
    pdf.multi_cell(0, 9, ar("ملخص التصميم"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("T", size=13)
    pdf.set_text_color(200, 220, 240)
    pdf.multi_cell(0, 7, ar("منصة المراقبة الذكية - نطاق الكلية"), align="C",
                  new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*DARK)
    pdf.set_y(70)

    pdf.heading("Database Design Overview", size=14, color=NAVY)
    pdf.rtl("Smart College Surveillance Platform (College Scope) - Sprint 1", size=11, bold=True, color=TEAL)
    pdf.rtl("المؤلف: محمد جهاد عبد المنعم - Backend & Frontend", size=10)
    pdf.rtl("التاريخ: 27 October 2026   |   التسليم: 28 October 2026", size=10)
    pdf.ln(4)

    pdf.box("ماذا أنجزنا", [
        "7 جداول أساسية (sites, users, cameras, camera_links, alerts, alert_actions, camera_health_events)",
        "5 جداول Phase-2 (recordings, tracked_persons, person_tracks, site_settings, audit_log)",
        "2 دوال write-path: decide_alert() و set_camera_status() (SECURITY DEFINER)",
        "2 views: camera_edges و alert_feed",
        "4 enums + triggers + 11 indexes",
        "ER diagram (PNG + SVG) مُولَّد من DBML",
        "21 فحص (validate_schema.py) + 17 تست (API spike)",
        "6 وثائق (database-design, er-diagram, team-agreement, api-contract, sprint1-report, README)",
    ])

    pdf.rtl("الهدف: تجميد \"الواجهة\" (interface) بين الـ AI services و الداتابيز و الداشبورد، "
            "بحيث يمكن للفريق العمل بالتوازي.", size=10, color=GREY)

    if ER_PNG.exists():
        pdf.ln(2)
        pdf.rtl("الـ ER diagram (7 جداول):", size=10.5, bold=True, color=NAVY)
        img_w = 95
        pdf.image(str(ER_PNG), x=(pdf.w - img_w) / 2, w=img_w)

    # ---------- Table of contents ----------
    pdf.ensure_new_page()
    pdf.header_band("فهرس الملفات", "File index - 13 ملفات تصميم + 4 مراجع")
    pdf.rtl("الهيكل (Structure):", size=11, bold=True, color=NAVY)
    pdf.ltr("""graduation-project/
  db/
    schema.postgres.sql          <- مصدر الحقيقة (7 جداول)
    schema.phase2.postgres.sql   <- إضافات مستقبلية (5 جداول)
    seed.sql                     <- بيانات تجريبية (idempotent)
    schema.dbml                  <- نموذج مرئي (dbdiagram.io)
  docs/
    database-design.md           <- الوثيقة الأم (19 قسم)
    er-diagram.md                <- صفحة واحدة مرئية
    diagrams/er-core.png|.svg    <- الرسم (مُولَّد)
    team-agreement.md            <- اتفاق الفريق
    api-contract.md              <- عقد الـ API
    sprint1-report.md            <- ملخص التسليم
  scripts/
    validate_schema.py           <- 21 فحص
    render_er.py                 <- مولد الرسم
  README.md                      <- الفهرس
  backend/                       <- API spike (parked)
  api/                           <- samples + openapi""")
    pdf.ln(2)
    pdf.rtl("قائمة الملفات (بالترتيب الموصى به):", size=11, bold=True, color=NAVY)
    for i, f in enumerate(FILES, 1):
        pdf.set_font("T", size=9.5)
        pdf.set_text_color(*DARK)
        pdf.cell(8, 5, f"{i}.", align="R", new_x="RIGHT", new_y="TOP")
        pdf.set_font("TB", size=9.5)
        pdf.set_text_color(*TEAL)
        pdf.cell(0, 5, f["path"], align="L", new_x="LMARGIN", new_y="NEXT")
    # ---------- Per-file pages ----------
    for f in FILES:
        pdf.ensure_new_page()
        pdf.header_band(f["path"], f["title"])
        pdf.kv("الموقع:", f["path"])
        pdf.kv("الهدف:", f["purpose"])
        pdf.ln(1)
        pdf.sub("المحتوى:", size=10.5, color=NAVY, space=1)
        for ln in f["contents"]:
            pdf.bullet(ln, size=9.5, mark="-")
        pdf.ln(1)
        pdf.sub("الأهمية / نقاط رئيسية:", size=10.5, color=NAVY, space=1)
        for ln in f["important"]:
            pdf.bullet(ln, size=9.5, mark="*")
        pdf.ln(1)
        pdf.kv("الاستخدام:", f["usage"], key_color=AMBER)
    # ---------- Relationships page ----------
    pdf.ensure_new_page()
    pdf.header_band("خريطة الترابط", "How the files relate")
    pdf.rtl("دورة التحديث (لو عدّلت شيئاً):", size=11, bold=True, color=NAVY)
    pdf.ltr("""1. عدّل  db/schema.postgres.sql
2. عدّل  db/schema.dbml  (نفس التغيير)
3. شغّل  python scripts/render_er.py
4. if fields changed:  docs/team-agreement.md  +  docs/api-contract.md
5. شغّل  python scripts/validate_schema.py
6. حدّث  docs/database-design.md  (أقسام 7 و 15)""")
    pdf.ln(2)
    pdf.rtl("الـ SQL هو \"إيه\" (what). الوثيقة هي \"ليه\" (why). الرسم هو \"شكل\". "
            "الـ validator هو \"إثبات\".", size=10.5, bold=True, color=TEAL)
    pdf.ln(2)
    pdf.rtl("أوامر سريعة:", size=11, bold=True, color=NAVY)
    pdf.ltr("""# تحقق من الـ Schema (21 فحص)
python scripts/validate_schema.py

# أعد توليد ER diagram
python scripts/render_er.py

# الـ API spike (parked)
cd backend && uvicorn app.main:app --reload --port 8000
cd backend && python -m pytest   # 17 passed""")
    pdf.ln(2)
    pdf.box("ملاحظة (OneDrive / git)", [
        "كل فولدر db/ كان untracked (git status -> ??).",
        "اختفى seed.sql مرة -> therefore commit now:",
        "git add graduation-project && git commit -m \"Database design v2\"",
        "كذلك build/ مُتجاهل (.gitignore) - لا تُلصق الصور يدويًا.",
    ], fill=(255, 245, 230), title_color=AMBER)

    pdf.output(str(OUT))
    print("wrote", OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    build()