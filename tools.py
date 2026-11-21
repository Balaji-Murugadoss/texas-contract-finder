"""The agent's tools: plain Python functions you can test without any AI.
tenant_id is injected by the harness from the logged-in session; the model never chooses it."""
import json
from datetime import datetime, timedelta
from urllib.parse import unquote_plus

import app_state
import config
import db
import docs
import fit

OPEN_TEXAS_STATUSES = ["Posted", "Addendum Posted"]
MIN_DAYS_FLOOR = 3          # business rule, enforced in code: the model can make it stricter, never looser
NIGP_MAP = json.loads((config.BASE_DIR / "reference" / "naics_to_nigp.json").read_text())

# One search per topic beats one search for everything. Wording measured where we could:
# the price-range question put the right chunk at rank 2 (one word of difference had missed it).
FIT_QUESTIONS = ["How and when must proposals be submitted?",
                 "What is the estimated price range (magnitude) of this project?",
                 "What bid bond, performance bond and payment bond are required?",
                 "Is this a small business set-aside and who is eligible?",
                 "What past performance, references and experience are required?",
                 "Where is the work performed and what site access or security rules apply?"]


def _tenant(tenant_id: str) -> dict:
    con = app_state.connect()
    t = app_state.get_tenant(con, tenant_id)
    con.close()
    if not t:
        raise ValueError(f"Unknown tenant {tenant_id}")
    return t


def _query(sql: str, params: list) -> list[dict]:
    con = db.connect(read_only=True)
    cur = con.execute(sql, params)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    con.close()
    return rows


def _naics(tenant: dict) -> list[str]:
    return [c.strip() for c in tenant["naics_codes"].split(",") if c.strip()]


def _nigp(naics_codes: list[str]) -> list[str]:
    """Texas uses NIGP codes, not NAICS: translate with the reviewed mapping file."""
    return sorted({code for n in naics_codes for code in NIGP_MAP.get(n, [])})


def search_opportunities(tenant_id: str, keywords: str | None = None, days_ahead: int = 30,
                         min_days_left: int = MIN_DAYS_FLOOR, place_of_performance: str | None = None,
                         source: str | None = None, limit: int = 10) -> dict:
    t = _tenant(tenant_id)
    naics = _naics(t)
    now = datetime.now()
    min_days_left = max(int(min_days_left), MIN_DAYS_FLOOR)
    sql = """SELECT opp_id, source, title, agency, notice_type, set_aside,
                    state AS place_of_performance, url,
                    strftime(response_deadline, '%Y-%m-%d %H:%M') || ' US Central' AS deadline
             FROM opportunities
             WHERE response_deadline BETWEEN ? AND ?
               AND ((source = 'sam' AND list_contains(?::VARCHAR[], naics))
                 OR (source = 'esbd' AND notice_type IN (SELECT unnest(?::VARCHAR[]))
                     AND opp_id IN (SELECT opp_id FROM opportunity_codes
                                    WHERE scheme = 'nigp' AND list_contains(?::VARCHAR[], code))))"""
    params: list = [now + timedelta(days=min_days_left), now + timedelta(days=int(days_ahead)),
                    naics, OPEN_TEXAS_STATUSES, _nigp(naics)]
    if place_of_performance:                       # unknown locations are kept, and shown as null
        sql += " AND (state = ? OR state IS NULL)"
        params.append(place_of_performance.upper())
    if source:
        sql += " AND source = ?"
        params.append(source)
    base_sql, base_params = sql, list(params)
    words = [w for w in keywords.replace(",", " ").split() if len(w) >= 3] if keywords else []
    if words:                                      # ANY word may match; 'it' would match 'maintenance'
        sql += " AND (" + " OR ".join(["title ILIKE ?"] * len(words)) + ")"
        params += [f"%{w}%" for w in words]
    order = " ORDER BY response_deadline LIMIT ?"
    cap = min(int(limit), 25)                      # context engineering: cap what the model sees
    results = _query(sql + order, params + [cap])
    out = {"results": results}
    if words and not results:                      # a tool can coach the model instead of returning nothing
        n = _query(f"SELECT COUNT(*) AS n FROM ({base_sql})", base_params)[0]["n"]
        out["hint"] = (f"No titles contain {words}, but {n} opportunities match this business's codes. "
                       "Search again without keywords.")
    out["data_freshness"] = _query("SELECT source, strftime(max(loaded_at), '%Y-%m-%d %H:%M') AS last_loaded "
                                   "FROM opportunities GROUP BY source", [])
    return out


def past_awards(tenant_id: str, naics: str | None = None, top_n: int = 5) -> dict:
    code = naics or _naics(_tenant(tenant_id))[0]
    summary = _query("SELECT COUNT(*) AS n, SUM(amount) AS total, MEDIAN(amount) AS median "
                     "FROM awards WHERE naics = ?", [code])[0]
    top = _query("SELECT recipient, COUNT(*) AS wins, SUM(amount) AS total FROM awards "
                 "WHERE naics = ? GROUP BY recipient ORDER BY total DESC LIMIT ?", [code, int(top_n)])
    # A summary, not 300 raw rows: the model needs the pattern, not the spreadsheet
    return {"naics": code, "awards": summary["n"], "total_usd": round(summary["total"] or 0),
            "median_usd": round(summary["median"] or 0),
            "note": "Largest awards only (USAspending sorted by amount), so this is not a full count.",
            "top_recipients": [{"recipient": r["recipient"], "wins": r["wins"],
                                "total_usd": round(r["total"] or 0)} for r in top]}


def _notice(opp_id: str) -> dict | None:
    rows = _query("SELECT * FROM opportunities WHERE opp_id = ?", [opp_id])
    return rows[0] if rows else None


def _store(notice: dict) -> dict | None:
    attachments = json.loads(notice["attachments_json"] or "[]")
    return docs.index_document(notice["opp_id"], attachments) if attachments else None


def read_document(tenant_id: str, opp_id: str, question: str) -> dict:
    _tenant(tenant_id)
    notice = _notice(opp_id)
    if not notice:
        return {"error": f"No opportunity {opp_id}"}
    if notice["source"] == "esbd":
        return {"error": "Texas ESBD documents can't be fetched automatically (the site disallows bots). "
                         f"Ask the user to open {notice['url']}"}
    store = _store(notice)
    if not store:
        return {"error": "This notice has no attachments. Answer from the notice fields only."}
    return {"opp_id": opp_id, "title": notice["title"],
            "files_read": f"{store['files_read']} of {store['files_total']}",
            "non_pdf_skipped": [unquote_plus(s) for s in store["skipped"]], "failed": store["failed"],
            "excerpts": docs.search(store, question)}


def check_fit(tenant_id: str, opp_id: str) -> dict:
    tenant = _tenant(tenant_id)
    notice = _notice(opp_id)
    if not notice:
        return {"error": f"No opportunity {opp_id}"}
    excerpts, seen = [], set()
    store = _store(notice) if notice["source"] == "sam" else None
    if store:
        for q in FIT_QUESTIONS:                     # query decomposition: one search per topic
            for hit in docs.search(store, q, k=3):
                key = (hit["file"], hit["page"], hit["text"][:60])
                if key not in seen:
                    seen.add(key)
                    excerpts.append(hit)
    notice = {k: v for k, v in notice.items() if k != "attachments_json"}
    return fit.check(tenant, notice, excerpts)


def save_match(tenant_id: str, opp_id: str, fit_score: int, reasons: str) -> dict:
    if not _notice(opp_id):
        return {"error": f"No opportunity {opp_id}: nothing saved"}   # the model can't save made-up IDs
    con = app_state.connect()
    app_state.save_match(con, tenant_id, opp_id, max(0, min(100, int(fit_score))), reasons)
    con.close()
    return {"saved": opp_id}


TOOLS = {f.__name__: f for f in [search_opportunities, past_awards, read_document, check_fit, save_match]}


def _fn(name, description, properties, required=()):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": list(required)}}}


TOOL_SCHEMAS = [
    _fn("search_opportunities", "Find open federal (SAM.gov) and Texas (ESBD) opportunities matching "
        "this business's industry codes, with deadlines between min_days_left and days_ahead from now.",
                {"keywords": {"type": "string", "description": "Optional. Leave empty for broad requests: results are "
                      "already filtered to this business's industry codes. Any listed word may match a title."},
         "days_ahead": {"type": "integer", "description": "Latest deadline, in days from now. Default 30"},
                  "min_days_left": {"type": "integer", "description": "Skip deadlines sooner than this. Minimum 3"},
         "place_of_performance": {"type": "string", "description": "2-letter state, e.g. TX. Unknown kept"},
         "source": {"type": "string", "enum": ["sam", "esbd"]},
         "limit": {"type": "integer", "description": "Max results, up to 25"}}),
    _fn("past_awards", "Summarize past federal contract awards in Texas for an industry code: "
        "how many, typical size, and who usually wins.",
        {"naics": {"type": "string", "description": "6-digit NAICS; defaults to the business's first code"}}),
    _fn("read_document", "Search the attached bid documents (PDFs) of one federal opportunity and return "
        "the most relevant excerpts with file names and page numbers.",
        {"opp_id": {"type": "string"}, "question": {"type": "string"}}, ["opp_id", "question"]),
    _fn("check_fit", "Assess how well this business fits one opportunity: score, verdict, reasons, "
        "missing requirements, deadline, citations.",
        {"opp_id": {"type": "string"}}, ["opp_id"]),
    _fn("save_match", "Save an opportunity to this business's shortlist. Only when the user asks.",
        {"opp_id": {"type": "string"}, "fit_score": {"type": "integer"}, "reasons": {"type": "string"}},
        ["opp_id", "fit_score", "reasons"]),
]


def run_tool(name: str, args: dict, tenant_id: str) -> dict:
    if name not in TOOLS:
        return {"error": f"Unknown tool {name}"}
    args.pop("tenant_id", None)                       # the model can't pick a tenant, even if it tries
    try:
        return TOOLS[name](tenant_id, **args)
    except Exception as exc:                          # return the error so the agent can recover
        return {"error": f"{type(exc).__name__}: {exc}"}
