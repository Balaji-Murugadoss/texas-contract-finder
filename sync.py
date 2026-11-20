"""The scheduled workflow (not an agent): pull every source, load raw -> serving, print row counts.
Run it by hand now, with cron later. It is the ONLY process that writes to DuckDB,
so stop the API / MCP server while it runs.

Example:  python sync.py --naics 238220 --state TX
ESBD only:  python sync.py --naics 238220 --skip sam usaspending
"""
import argparse
import logging
import sys

import db
import esbd
import sam
import usaspending


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--naics", required=True)
    p.add_argument("--state", default="TX")
    p.add_argument("--days-back", type=int, default=30)
    p.add_argument("--skip", nargs="*", default=[], choices=["sam", "usaspending", "esbd"])
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)   # httpx logs full URLs, which include the SAM key

    con = db.connect()
    if "sam" not in a.skip:
        try:
            data = sam.search(con, naics=a.naics, state=a.state, days_back=a.days_back)
            n = sam.load(con, data)
            print(f"SAM.gov: {n} loaded (API says totalRecords={data.get('totalRecords')})")
            if n == 0:
                print("  WARNING: zero records. Check filters and the raw response before trusting this.")
        except sam.BudgetExceeded as exc:
            print(f"SAM.gov skipped: {exc}")
    if "usaspending" not in a.skip:
        rows = usaspending.fetch_awards(a.naics, a.state)
        print(f"USAspending: {usaspending.load(con, rows, a.naics, a.state)} awards loaded")
    if "esbd" not in a.skip:
        s = esbd.load_drop(con)
        print(f"Texas ESBD: {s['loaded']} solicitations from {s['files']} file(s). Read {s['rows_read']}, "
              f"duplicates {s['duplicates']}, no ID {s['skipped_no_id']}, no deadline {s['no_deadline']}, "
              f"bad files {s['bad_files']}")
        if s["rows_read"] != s["loaded"] + s["duplicates"] + s["skipped_no_id"]:
            print("  WARNING: rows don't balance. Investigate before trusting this load.")

    for table in ["raw_sam", "raw_esbd", "opportunities", "opportunity_codes", "awards", "api_cache"]:
        print(f"  {table}: {con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]} rows")
    con.close()


if __name__ == "__main__":
    main()
