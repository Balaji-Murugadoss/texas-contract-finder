"""Texas ESBD loader. ESBD has no API, and its robots.txt disallows all bots, so this code never calls it.
A person clicks "Export to CSV" on txsmartbuy.gov/esbd and drops the file in data/esbd_drop/.
Same job as an SFTP drop from a client: validate each file, then bulk-load raw -> serving."""
import csv
import json
import logging
import re
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger(__name__)

DROP_DIR = config.DATA_DIR / "esbd_drop"
DETAIL_URL = "https://www.txsmartbuy.gov/esbd/{}"
EXPORT_CAP = 20_000      # the portal says "CSV export is limited to 20,000 results"
REQUIRED = ["Name", "Solicitation ID", "Due Date", "Due Time", "Agency/Texas SmartBuy Member Number",
            "Status", "Posting Date", "Last Modified", "NIGP Codes"]


class BadFile(Exception):
    """The file can't be trusted (unreadable, empty, or the columns changed). Skip it and tell a person."""


def read_file(path: Path) -> list[dict]:
    for encoding in ("utf-8-sig", "cp1252"):      # utf-8-sig drops the invisible BOM; cp1252 = old Windows files
        try:
            with open(path, newline="", encoding=encoding) as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            break
        except UnicodeDecodeError:
            log.warning("%s is not %s, trying the next encoding", path.name, encoding)
    else:
        raise BadFile(f"{path.name}: unreadable text encoding")
    missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
    if missing:
        raise BadFile(f"{path.name}: missing columns {missing}. Did the export format change?")
    if not rows:
        raise BadFile(f"{path.name}: header only, no rows")
    if len(rows) >= EXPORT_CAP:
        log.warning("%s has %d rows, at the %d export cap, so it is probably cut off. Narrow the search, re-export.",
                    path.name, len(rows), EXPORT_CAP)
    log.info("%s: %d rows", path.name, len(rows))
    return rows


def _parse_date(text):
    try:
        return datetime.strptime(text.strip(), "%m/%d/%Y").date()
    except (ValueError, AttributeError):
        return None


def parse_deadline(day, clock):
    """ESBD splits the deadline into two columns. Texas solicitations say 'all times are Central Time',
    so we store Central, same as SAM after its conversion. No time given -> midnight, the earliest
    possible, so we never show a deadline later than the real one."""
    d = _parse_date(day)
    if d is None:
        return None
    try:
        t = datetime.strptime(clock.strip().upper(), "%I:%M %p").time()
    except (ValueError, AttributeError):
        t = datetime.min.time()
    return datetime.combine(d, t)


def _modified(row):
    try:
        return datetime.strptime(row["Last Modified"].strip().upper(), "%m/%d/%Y %I:%M %p")
    except (ValueError, AttributeError):
        return datetime.min


CODE_PART = re.compile(r"^(\d{5})(?:-(.*))?$", re.S)     # 5 digits, then optionally "-label"


def nigp_codes(text) -> dict:
    """The NIGP field is messy. All four cases below came from the real export:
      '03167-Hvac Supplies;'      code-label pairs that end with ';'
      '...<line break>91450'      extra codes on new lines, with no label
      '(see 805-xx; and 805-51)'  a ';' inside a label
      'Training, E(more...)'      the portal cut the text off; the codes after it are lost
    Returns {'03167': 'Hvac Supplies', '91450': '', ...}"""
    codes, last = {}, None
    for part in re.split(r";|[\r\n]+", (text or "").replace("(more...)", "")):
        part = part.strip()
        m = CODE_PART.match(part)
        if m:
            last = m.group(1)
            codes[last] = codes.get(last) or (m.group(2) or "").strip()
        elif part and last:
            codes[last] += "; " + part        # a ';' inside the label split it: glue it back
    return codes


def load_drop(con, folder=DROP_DIR) -> dict:
    """Read every CSV in the drop folder, keep the newest version of each solicitation,
    and replace the Texas data with it. The drop folder is the source of truth."""
    stats = {"files": 0, "bad_files": [], "rows_read": 0, "duplicates": 0, "skipped_no_id": 0,
             "no_deadline": 0, "codes_cut_off": 0, "loaded": 0}
    newest = {}
    for path in sorted(Path(folder).glob("*.csv")):
        stats["files"] += 1
        try:
            rows = read_file(path)
        except BadFile as exc:
            log.error("%s", exc)
            stats["bad_files"].append(path.name)
            continue
        for row in rows:
            stats["rows_read"] += 1
            sid = (row.get("Solicitation ID") or "").strip()
            if not sid:
                stats["skipped_no_id"] += 1
                continue
            if sid in newest:
                stats["duplicates"] += 1
                if _modified(row) < _modified(newest[sid]):
                    continue                          # keep the most recently modified version
            newest[sid] = row
    if not newest:
        return stats

    # Build one Python list per column. DuckDB loads whole columns at once:
    # row-by-row inserts of 56,000 rows took minutes, this takes under a second.
    cols = {k: [] for k in ["sid", "payload", "title", "agency", "status", "posted", "deadline", "url"]}
    code_cols = {"opp_id": [], "code": [], "label": []}
    for sid, row in newest.items():
        deadline = parse_deadline(row["Due Date"], row["Due Time"])
        stats["no_deadline"] += deadline is None
        stats["codes_cut_off"] += "(more...)" in row["NIGP Codes"]
        cols["sid"].append(sid)
        cols["payload"].append(json.dumps(row))
        cols["title"].append(row["Name"].strip())
        cols["agency"].append(f"TX member {row['Agency/Texas SmartBuy Member Number'].strip()}")
        cols["status"].append(row["Status"].strip())
        cols["posted"].append(_parse_date(row["Posting Date"]))
        cols["deadline"].append(deadline)
        cols["url"].append(DETAIL_URL.format(sid))
        for code, label in nigp_codes(row["NIGP Codes"]).items():
            code_cols["opp_id"].append(f"esbd:{sid}")
            code_cols["code"].append(code)
            code_cols["label"].append(label)

    if stats["codes_cut_off"]:
        log.warning("%d postings have NIGP codes cut off by the export ('(more...)'): some codes are missing",
                    stats["codes_cut_off"])

    now = datetime.now()
    con.execute("CREATE OR REPLACE TEMP TABLE esbd_stage AS SELECT unnest($sid) AS sid, "
                "unnest($payload) AS payload, unnest($title) AS title, unnest($agency) AS agency, "
                "unnest($status) AS status, unnest($posted)::DATE AS posted, "
                "unnest($deadline)::TIMESTAMP AS deadline, unnest($url) AS url", cols)
    # Each export is a full snapshot of the open postings, so replace the whole Texas slice.
    # One transaction: if anything fails, nothing changes (no half-empty tables).
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute("DELETE FROM opportunity_codes WHERE scheme = 'nigp'")
        con.execute("DELETE FROM opportunities WHERE source = 'esbd'")
        con.execute("DELETE FROM raw_esbd")
        con.execute("INSERT INTO raw_esbd SELECT sid, payload, $now FROM esbd_stage", {"now": now})
        con.execute("INSERT INTO opportunities SELECT 'esbd:' || sid, 'esbd', title, agency, NULL, "
                    "status, NULL, 'TX', posted, deadline, url, '[]', $now FROM esbd_stage", {"now": now})
        if code_cols["code"]:
            con.execute("INSERT INTO opportunity_codes "
                        "SELECT unnest($opp_id), 'nigp', unnest($code), unnest($label)", code_cols)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    stats["loaded"] = len(newest)
    return stats
