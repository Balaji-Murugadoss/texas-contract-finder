"""USAspending.gov: no key, POST with JSON filters. Past federal awards = who wins, for how much."""
import time
from datetime import datetime

from net import request_with_retry

URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
FIELDS = ["Award ID", "Recipient Name", "Award Amount", "Start Date", "Awarding Agency", "Description"]


def fetch_awards(naics: str, state: str = "TX", start: str = "2023-10-01",
                 end: str = "2026-09-30", max_pages: int = 3) -> list[dict]:
    rows = []
    for page in range(1, max_pages + 1):
        body = {
            "filters": {
                "award_type_codes": ["A", "B", "C", "D"],          # contracts only
                "naics_codes": [naics],
                "place_of_performance_locations": [{"country": "USA", "state": state}],
                "time_period": [{"start_date": start, "end_date": end}],
            },
            "fields": FIELDS, "page": page, "limit": 100,
            "sort": "Award Amount", "order": "desc",
        }
        data = request_with_retry("POST", URL, json=body).json()
        rows.extend(data.get("results", []))
        if not (data.get("page_metadata") or {}).get("hasNext"):
            break
        time.sleep(1)   # be polite even when there's no stated limit
    return rows


def load(con, rows: list[dict], naics: str, state: str) -> int:
    now = datetime.now()
    for r in rows:
        award_id = r.get("generated_internal_id") or r.get("Award ID")
        con.execute("INSERT OR REPLACE INTO awards VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            award_id, r.get("Recipient Name"), r.get("Award Amount"), r.get("Start Date"),
            r.get("Awarding Agency"), naics, state, r.get("Description"), now])
    return len(rows)
