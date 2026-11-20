"""DuckDB = the analytics store: raw data, clean data, and the tables the agent reads."""
from pathlib import Path

import duckdb

import config

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS api_cache (
        cache_key TEXT PRIMARY KEY, source TEXT, response_json TEXT, fetched_at TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS api_usage (
        source TEXT, day DATE, calls INTEGER, PRIMARY KEY (source, day))""",
    # raw layer: exactly what each source sent us
    """CREATE TABLE IF NOT EXISTS raw_sam (
        notice_id TEXT PRIMARY KEY, payload_json TEXT, loaded_at TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS raw_esbd (
        solicitation_id TEXT PRIMARY KEY, payload_json TEXT, loaded_at TIMESTAMP)""",
    # serving layer: one shape for every source
    """CREATE TABLE IF NOT EXISTS opportunities (
        opp_id TEXT PRIMARY KEY, source TEXT, title TEXT, agency TEXT, naics TEXT,
        notice_type TEXT, set_aside TEXT, state TEXT, posted_date DATE,
        response_deadline TIMESTAMP, url TEXT, attachments_json TEXT, loaded_at TIMESTAMP)""",
    # one row per (opportunity, code): a notice can have many codes, from different systems (NAICS, NIGP)
    """CREATE TABLE IF NOT EXISTS opportunity_codes (
        opp_id TEXT, scheme TEXT, code TEXT, label TEXT, PRIMARY KEY (opp_id, scheme, code))""",
    """CREATE TABLE IF NOT EXISTS awards (
        award_id TEXT PRIMARY KEY, recipient TEXT, amount DOUBLE, start_date DATE,
        agency TEXT, naics TEXT, state TEXT, description TEXT, loaded_at TIMESTAMP)""",
]


def connect(read_only: bool = False, path=None):
    """Writers: sync.py only. The agent, API and MCP server open it read-only."""
    path = str(path or config.DB_PATH)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    if read_only:
        return duckdb.connect(path, read_only=True)
    con = duckdb.connect(path)
    for statement in SCHEMA:
        con.execute(statement)
    return con
