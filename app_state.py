"""SQLite = the app's own state (tenants, saved matches). Small, transactional, safe for many readers/writers.
Every query filters on tenant_id: that is the isolation rule, enforced here and nowhere else."""
import sqlite3
from datetime import datetime
from pathlib import Path

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id TEXT PRIMARY KEY, api_key TEXT UNIQUE, name TEXT, naics_codes TEXT,
    state TEXT, certifications TEXT, employees INTEGER, notes TEXT);
CREATE TABLE IF NOT EXISTS saved_matches (
    tenant_id TEXT, opp_id TEXT, fit_score INTEGER, reasons TEXT, saved_at TEXT,
    PRIMARY KEY (tenant_id, opp_id));
"""


def connect(path=None):
    path = str(path or config.APP_DB_PATH)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def upsert_tenant(con, **t):
    con.execute("INSERT OR REPLACE INTO tenants VALUES (:tenant_id, :api_key, :name, :naics_codes, "
                ":state, :certifications, :employees, :notes)", t)
    con.commit()


def get_tenant(con, tenant_id: str):
    row = con.execute("SELECT * FROM tenants WHERE tenant_id=?", [tenant_id]).fetchone()
    return dict(row) if row else None


def tenant_for_api_key(con, api_key: str):
    row = con.execute("SELECT * FROM tenants WHERE api_key=?", [api_key]).fetchone()
    return dict(row) if row else None


def save_match(con, tenant_id: str, opp_id: str, fit_score: int, reasons: str):
    con.execute("INSERT OR REPLACE INTO saved_matches VALUES (?, ?, ?, ?, ?)",
                [tenant_id, opp_id, fit_score, reasons, datetime.now().isoformat()])
    con.commit()


def list_matches(con, tenant_id: str) -> list[dict]:
    rows = con.execute("SELECT * FROM saved_matches WHERE tenant_id=? ORDER BY fit_score DESC",
                       [tenant_id]).fetchall()
    return [dict(r) for r in rows]
