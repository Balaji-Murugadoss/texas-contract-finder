"""SAM.gov Get Opportunities API: a real API with a key and a small daily quota.
Protect the quota with a budget counter and a cache."""
import hashlib
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import config
from net import request_with_retry

URL = "https://api.sam.gov/opportunities/v2/search"
CENTRAL = ZoneInfo("America/Chicago")   


class BudgetExceeded(Exception):
    pass


def _cache_key(params: dict) -> str:
    safe = {k: v for k, v in params.items() if k != "api_key"}   # never store the key
    return hashlib.sha256(json.dumps(safe, sort_keys=True).encode()).hexdigest()


def _use_budget(con, source: str = "sam") -> None:
    today = date.today()
    row = con.execute("SELECT calls FROM api_usage WHERE source=? AND day=?", [source, today]).fetchone()
    used = row[0] if row else 0
    if used >= config.SAM_DAILY_BUDGET:
        raise BudgetExceeded(f"SAM.gov budget used up for today ({used}/{config.SAM_DAILY_BUDGET})")
    con.execute("INSERT OR REPLACE INTO api_usage VALUES (?, ?, ?)", [source, today, used + 1])


def search(con, *, naics: str, state: str = "TX", days_back: int = 30,
           ptypes: str = "o,k,p,r", limit: int = 1000) -> dict:
    """One page of results. Cache first; spend budget only on a cache miss."""
    today = date.today()
    params = {
        "postedFrom": (today - timedelta(days=days_back)).strftime("%m/%d/%Y"),
        "postedTo": today.strftime("%m/%d/%Y"),
        "ncode": naics, "state": state, "ptype": ptypes, "limit": limit, "offset": 0,
    }
    key = _cache_key(params)
    cutoff = datetime.now() - timedelta(hours=config.CACHE_HOURS)
    hit = con.execute("SELECT response_json FROM api_cache WHERE cache_key=? AND fetched_at > ?",
                      [key, cutoff]).fetchone()
    if hit:
        return json.loads(hit[0])

    _use_budget(con)
    resp = request_with_retry("GET", URL, params={**params, "api_key": config.SAM_API_KEY})
    data = resp.json()
    con.execute("INSERT OR REPLACE INTO api_cache VALUES (?, 'sam', ?, ?)",
                [key, json.dumps(data), datetime.now()])
    return data


def _parse_dt(value):
    """Text -> datetime in Central time. SAM sends each deadline in the agency's own time zone."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo:
        dt = dt.astimezone(CENTRAL)
    return dt.replace(tzinfo=None)


def normalize(o: dict) -> dict:
    """Map one SAM record to our common shape. Use .get(): fields go missing in real data."""
    place = o.get("placeOfPerformance") or {}
    state = (place.get("state") or {}).get("code")
    posted = _parse_dt(o.get("postedDate"))
    return {
        "opp_id": f"sam:{o['noticeId']}",
        "source": "sam",
        "title": o.get("title"),
        "agency": o.get("fullParentPathName"),
        "naics": o.get("naicsCode"),
        "notice_type": o.get("type"),
        "set_aside": o.get("typeOfSetAsideDescription") or o.get("typeOfSetAside"),
        "state": state,
        "posted_date": posted.date() if posted else None,
        "response_deadline": _parse_dt(o.get("responseDeadLine")),
        "url": o.get("uiLink"),
        "attachments_json": json.dumps(o.get("resourceLinks") or []),
    }


def load(con, data: dict) -> int:
    """Raw layer, then serving layer. Re-running is safe (idempotent)."""
    now = datetime.now()
    records = data.get("opportunitiesData") or []
    for o in records:
        con.execute("INSERT OR REPLACE INTO raw_sam VALUES (?, ?, ?)", [o["noticeId"], json.dumps(o), now])
        row = normalize(o)
        con.execute("INSERT OR REPLACE INTO opportunities VALUES "
                    "($opp_id, $source, $title, $agency, $naics, $notice_type, $set_aside, $state, "
                    "$posted_date, $response_deadline, $url, $attachments_json, $loaded_at)",
                    {**row, "loaded_at": now})
    return len(records)
