"""Eval harness: run every case through the real agent, check the answer, save a results table.
Run the SAME cases after every change (prompt, tool, model) and compare the pass rate.

Examples:
  python evals.py --label baseline
  python evals.py --label nano --model gpt-5.4-nano
  python evals.py --label baseline-x3 --repeat 3
"""
import argparse
import csv
import json
import re
from pathlib import Path

import config
from agent import run_agent

REFUSAL_WORDS = ["can't help", "cannot help", "can only", "only help with", "not able to help", "outside"]


def check(rule: dict, out: dict) -> bool:
    """One rule, one yes/no. The rules look at the answer text and at which tools the agent used."""
    answer = (out["answer"] or "").lower().replace("\u2019", "'").replace("\u2018", "'")   # ’ and ‘ count as '
    steps = out["steps"]
    kind = rule["type"]
    if kind == "contains_any":
        return any(text.lower() in answer for text in rule["values"])
    if kind == "not_contains":
        return all(text.lower() not in answer for text in rule["values"])
    if kind == "tool_used":
        return any(s["tool"] == rule["tool"] for s in steps)
    if kind == "tool_count":
        return sum(s["tool"] == rule["tool"] for s in steps) >= rule["min"]
    if kind == "searched_broadly":
        return any(s["tool"] == "search_opportunities" and isinstance(s["args"], dict)
                   and not s["args"].get("keywords") for s in steps)
    if kind == "min_links":
        return len(set(re.findall(r"https?://[^\s)|>\]]+", answer))) >= rule["min"]
    if kind == "refuses":
        return not steps and any(w in answer for w in REFUSAL_WORDS)
    raise ValueError(f"Unknown rule type {kind}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--label", required=True)
    p.add_argument("--model", default=config.MODEL)
    p.add_argument("--repeat", type=int, default=1, help="run each case N times: answers vary run to run")
    p.add_argument("--cases", default="evals/cases.jsonl")
    a = p.parse_args()

    cases = [json.loads(line) for line in Path(a.cases).read_text().splitlines() if line.strip()]
    rows = []
    for case in cases:
        for attempt in range(1, a.repeat + 1):
            out = run_agent(case["tenant_id"], case["question"], model=a.model)
            failed = [r["type"] for r in case["checks"] if not check(r, out)]
            rows.append({"id": case["id"], "attempt": attempt, "passed": not failed,
                         "failed_checks": "|".join(failed), "seconds": out["seconds"], "cost_usd": out["cost_usd"],
                         "tools": "|".join(s["tool"] for s in out["steps"]),
                         "answer": (out["answer"] or "")[:300].replace("\n", " ")})
            print(f"{'PASS' if not failed else 'FAIL'}  {case['id']}  "
                  f"{'(failed: ' + ', '.join(failed) + ')' if failed else ''}  {out['seconds']}s  ${out['cost_usd']}")

    Path("evals/results").mkdir(parents=True, exist_ok=True)
    with open(f"evals/results/{a.label}.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    n, passed = len(rows), sum(r["passed"] for r in rows)
    print(f"\n{a.label}: {passed}/{n} passed ({passed / n:.0%}) | avg {sum(r['seconds'] for r in rows) / n:.1f}s "
          f"| total ${sum(r['cost_usd'] for r in rows):.3f} | model {a.model}")


if __name__ == "__main__":
    main()
