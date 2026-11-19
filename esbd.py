"""Texas ESBD: no documented API. You find the portal's own JSON calls in DevTools,
then fill in the three TODOs below. Be polite: one request every few seconds, honest User-Agent."""
import json
import time
from datetime import datetime

from net import request_with_retry

SEARCH_URL = "TODO: paste the request URL you found in DevTools"
BASE_PARAMS: dict = {}          # TODO: the query params / body fields the portal sends
FIELD_MAP = {                    # TODO: our column -> the portal's field name, from your profiling
    "id": "TODO", "title": "TODO", "agency": "TODO",
    "deadline": "TODO", "posted": "TODO", "url": "TODO",
}


def fetch(keyword: str, max_pages: int = 3, pause_seconds: float = 3.0) -> list[dict]:
    items = []
    for page in range(1, max_pages + 1):
        params = {**BASE_PARAMS, "keyword": keyword, "page": page}   # adjust names to match the portal
        data = request_with_retry("GET", SEARCH_URL, params=params).json()
        batch = data.get("items") or data.get("results") or []     # adjust to the real shape
        if not batch:
            break
        items.extend(batch)
        time.sleep(pause_seconds)
    return items


def normalize(item: dict) -> dict:
    get = lambda col: item.get(FIELD_MAP[col])
    return {
        "opp_id": f"esbd:{get('id')}", "source": "esbd", "title": get("title"),
        "agency": get("agency"), "naics": None,   # ESBD uses NIGP codes, not NAICS: note it, don't fake it
        "notice_type": "Solicitation", "set_aside": None, "state": "TX",
        "posted_date": get("posted"), "response_deadline": get("deadline"),
        "url": get("url"), "attachments_json": "[]",
    }


def load(con, items: list[dict]) -> int:
    now = datetime.now()
    for item in items:
        row = normalize(item)
        con.execute("INSERT OR REPLACE INTO raw_esbd VALUES (?, ?, ?)", [row["opp_id"], json.dumps(item), now])
        con.execute("INSERT OR REPLACE INTO opportunities VALUES "
                    "($opp_id, $source, $title, $agency, $naics, $notice_type, $set_aside, $state, "
                    "$posted_date, $response_deadline, $url, $attachments_json, $loaded_at)",
                    {**row, "loaded_at": now})
    return len(items)
