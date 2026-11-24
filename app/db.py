"""SQLite 데이터베이스 (V1). 운영 규모가 커지면 PostgreSQL로 교체할 수 있도록 SQL을 단순하게 유지한다."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'customer',          -- customer | admin
    free_trial_used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    industry TEXT NOT NULL,
    address TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    website TEXT NOT NULL DEFAULT '',
    products TEXT NOT NULL DEFAULT '',
    logo_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    product_code TEXT NOT NULL DEFAULT 'free_trial',
    purpose TEXT NOT NULL DEFAULT '',
    target_age TEXT NOT NULL DEFAULT '',
    mood TEXT NOT NULL DEFAULT '',
    style TEXT NOT NULL DEFAULT 'trend',
    duration INTEGER NOT NULL DEFAULT 30,
    reference_links TEXT NOT NULL DEFAULT '',
    request_note TEXT NOT NULL DEFAULT '',
    highlights TEXT NOT NULL DEFAULT '',     -- 고객이 직접 입력한 강조 문구(자막에 그대로 사용)
    status TEXT NOT NULL DEFAULT 'received',
    -- received | processing | review | delivered | revision | failed | canceled
    price INTEGER NOT NULL DEFAULT 0,
    paid INTEGER NOT NULL DEFAULT 0,
    rating INTEGER,
    feedback TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    kind TEXT NOT NULL,                 -- video | image
    original_name TEXT NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    probe_json TEXT NOT NULL DEFAULT '{}',
    analysis_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS renders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    version INTEGER NOT NULL,
    style TEXT NOT NULL,
    duration INTEGER NOT NULL,
    plan_json TEXT NOT NULL DEFAULT '{}',
    output_path TEXT NOT NULL DEFAULT '',
    thumb_path TEXT NOT NULL DEFAULT '',
    sns_json TEXT NOT NULL DEFAULT '{}',
    cost_json TEXT NOT NULL DEFAULT '{}',
    approved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,                 -- produce | analyze_reference
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued',  -- queued | running | done | failed | awaiting_approval
    progress INTEGER NOT NULL DEFAULT 0,
    step TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    log TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS references_db (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    industry TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'manual',
    url TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    video_path TEXT NOT NULL DEFAULT '',
    analyzed_at TEXT,
    metrics_json TEXT NOT NULL DEFAULT '{}',   -- 각 값에 source(api|manual) 표시
    duration_sec REAL,
    cut_count INTEGER,
    avg_cut_sec REAL,
    hook_type TEXT NOT NULL DEFAULT '',
    hook_text TEXT NOT NULL DEFAULT '',
    edit_pattern TEXT NOT NULL DEFAULT '',
    caption_style TEXT NOT NULL DEFAULT '',
    caption_position TEXT NOT NULL DEFAULT '',
    music_mood TEXT NOT NULL DEFAULT '',
    story_structure TEXT NOT NULL DEFAULT '',
    cta_type TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    ai_summary TEXT NOT NULL DEFAULT '',
    template_style TEXT NOT NULL DEFAULT '',
    reliability TEXT NOT NULL DEFAULT 'low',   -- low | medium | high
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS music (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    mood TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL,
    bpm REAL,
    duration_sec REAL,
    license_source TEXT NOT NULL,       -- 출처
    license_terms TEXT NOT NULL,        -- 이용 조건 (상업적 이용 허용 확인)
    commercial_ok INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    videos INTEGER NOT NULL DEFAULT 1,
    period TEXT NOT NULL DEFAULT 'once',   -- once | monthly | quote
    active INTEGER NOT NULL DEFAULT 1,
    sort INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER REFERENCES orders(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    amount INTEGER NOT NULL,
    method TEXT NOT NULL DEFAULT 'manual',  -- manual(계좌이체 등 수동확인) | test
    status TEXT NOT NULL DEFAULT 'paid',
    memo TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    requested_by TEXT NOT NULL,         -- customer | admin
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_media_order ON media(order_id);
"""

DEFAULT_PRODUCTS = [
    ("free_trial", "신규 고객 무료 체험 1편", 0, 1, "once", 0),
    ("basic", "기본 숏폼 1편", 19900, 1, "once", 1),
    ("premium", "프리미엄 숏폼 1편", 39900, 1, "once", 2),
    ("monthly_4", "월 4편 제작", 99000, 4, "monthly", 3),
    ("monthly_12", "월 12편 제작", 249000, 12, "monthly", 4),
    ("monthly_30", "월 30편 제작", 499000, 30, "monthly", 5),
    ("enterprise", "기업 맞춤형 (별도 견적)", 0, 0, "quote", 6),
]

DEFAULT_SETTINGS = {
    "monthly_ai_budget_krw": "50000",      # 월 AI 사용료 한도
    "monthly_server_budget_krw": "50000",  # 월 서버비 한도
    "per_job_cost_limit_krw": "1000",      # 1편 예상원가가 이 값을 넘으면 관리자 승인 필요
    "server_monthly_cost_krw": "15000",    # 원가 배분용 서버 월 고정비 (관리자 입력)
    "expected_monthly_videos": "100",
    "retention_days": str(config.RETENTION_DAYS),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def get() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = connect()
        _local.conn = conn
    return conn


@contextmanager
def tx():
    conn = get()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def init() -> None:
    conn = get()
    conn.executescript(SCHEMA)
    for p in DEFAULT_PRODUCTS:
        conn.execute(
            "INSERT OR IGNORE INTO products(code,name,price,videos,period,sort) VALUES (?,?,?,?,?,?)", p
        )
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)", (k, v))


def q(sql: str, args=()) -> list[dict]:
    return [dict(r) for r in get().execute(sql, args).fetchall()]


def q1(sql: str, args=()) -> dict | None:
    r = get().execute(sql, args).fetchone()
    return dict(r) if r else None


def run(sql: str, args=()) -> int:
    cur = get().execute(sql, args)
    return cur.lastrowid


def setting(key: str, default: str = "") -> str:
    r = q1("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else default


def jload(s: str | None, default=None):
    try:
        return json.loads(s) if s else (default if default is not None else {})
    except (TypeError, ValueError):
        return default if default is not None else {}


def jdump(o) -> str:
    return json.dumps(o, ensure_ascii=False)
