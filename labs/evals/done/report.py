"""Part 2: the score report. Pass rate by category, by check, and every failure listed.

A case passes when every code check passes AND (if it was judged) the judge passes it.

    uv run python labs/evals/done/report.py        # out/report.md and out/report.html
"""

from __future__ import annotations

import argparse
import html
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from cases import CATEGORIES, LAB, read_jsonl

OUT = LAB / "out"
CHECKS = ("days", "handover", "must_not", "amounts")


def judged(row: dict[str, Any]) -> bool:
    return bool(row.get("judge")) and "verdict" in row["judge"]


def passed(row: dict[str, Any]) -> bool:
    if not row.get("code_pass"):
        return False
    return row["judge"]["verdict"] == "pass" if judged(row) else True


def rate(ok: int, n: int) -> str:
    return f"{ok}/{n} ({ok / n:.0%})" if n else "-"


def build(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Every number the report shows, computed once for both formats."""
    by_cat = []
    for cat in (*CATEGORIES, "all"):
        sub = rows if cat == "all" else [r for r in rows if r["category"] == cat]
        if not sub:
            continue
        j = [r for r in sub if judged(r)]
        by_cat.append({
            "category": cat, "cases": len(sub),
            "code": rate(sum(bool(r["code_pass"]) for r in sub), len(sub)),
            "judge": rate(sum(r["judge"]["verdict"] == "pass" for r in j), len(j)),
            "overall": rate(sum(passed(r) for r in sub), len(sub)),
        })
    by_check = []
    for name in CHECKS:
        results = [c["passed"] for r in rows for c in r.get("checks", []) if c["name"] == name]
        applies = [x for x in results if x is not None]
        by_check.append({"check": name, "applies": len(applies), "pass": sum(applies),
                         "fail": len(applies) - sum(applies)})
    j = [r for r in rows if judged(r)]
    for name in ("grounded", "follows_policy", "answers_question"):
        ok = sum(r["judge"][name] == "pass" for r in j)
        by_check.append({"check": f"judge: {name}", "applies": len(j), "pass": ok, "fail": len(j) - ok})

    failures = []
    for r in rows:
        if passed(r):
            continue
        why = [f"{c['name']}: {c['note']}" for c in r.get("checks", []) if c["passed"] is False]
        if r.get("error"):
            why.append(f"error: {r['error']}")
        if judged(r) and r["judge"]["verdict"] == "fail":
            failed = [k for k in ("grounded", "follows_policy", "answers_question") if r["judge"][k] == "fail"]
            why.append(f"judge ({', '.join(failed)}): {r['judge']['reason']}")
        failures.append({"id": r["id"], "category": r["category"], "question": r["question"],
                         "reply": r.get("reply") or "", "handover": r.get("handover"), "why": why})

    first = rows[0] if rows else {}
    judge_models = Counter(r["judge"]["model"] for r in j)
    return {
        "date": date.today().isoformat(), "cases": len(rows), "judged": len(j),
        "model": f"{first.get('provider')} {first.get('model')}", "prompt": first.get("prompt_version"),
        "judge": ", ".join(judge_models) or "none",
        "overall": rate(sum(passed(r) for r in rows), len(rows)),
        "by_cat": by_cat, "by_check": by_check, "failures": failures,
        "cost": sum(r.get("cost_usd") or 0 for r in rows) + sum(r["judge"]["cost_usd"] for r in j),
    }


def to_markdown(d: dict[str, Any]) -> str:
    out = [
        "# ShopKart Copilot: eval report", "",
        f"{d['date']} · {d['cases']} cases · Copilot {d['model']}, prompt {d['prompt']} · "
        f"judge {d['judge']} on {d['judged']} cases", "",
        f"**Overall pass rate: {d['overall']}** (all code checks pass, and the judge passes it if judged)", "",
        "## By category", "",
        "| Category | Cases | Code checks | Judge | Overall |", "| --- | ---: | ---: | ---: | ---: |",
    ]
    out += [f"| {c['category']} | {c['cases']} | {c['code']} | {c['judge']} | {c['overall']} |" for c in d["by_cat"]]
    out += ["", "## By check", "", "| Check | Applies to | Pass | Fail |", "| --- | ---: | ---: | ---: |"]
    out += [f"| {c['check']} | {c['applies']} | {c['pass']} | {c['fail']} |" for c in d["by_check"]]
    out += ["", f"## Failures ({len(d['failures'])})", ""]
    if not d["failures"]:
        out.append("None.")
    for f in d["failures"]:
        out += [f"### {f['id']} · {f['category']}", "", f"**Q:** {f['question']}", "",
                f"**A** (handover={str(f['handover']).lower()}): {f['reply']}", ""]
        out += [f"- {w}" for w in f["why"]]
        out.append("")
    out.append(f"New spend for this run: ${d['cost']:.6f} (cached answers cost $0).")
    return "\n".join(out) + "\n"


def to_html(d: dict[str, Any]) -> str:
    e = html.escape

    def table(head: list[str], rows: list[list[Any]]) -> str:
        th = "".join(f"<th>{e(h)}</th>" for h in head)
        tr = "".join("<tr>" + "".join(f"<td>{e(str(x))}</td>" for x in r) + "</tr>" for r in rows)
        return f"<table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>"

    fails = "".join(
        f"<details><summary><b>{e(f['id'])}</b> · {e(f['category'])} · {e(f['question'])}</summary>"
        f"<p class=a><b>Answer</b> (handover={str(f['handover']).lower()}): {e(f['reply'])}</p>"
        "<ul>" + "".join(f"<li>{e(w)}</li>" for w in f["why"]) + "</ul></details>"
        for f in d["failures"]) or "<p>None.</p>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ShopKart eval report</title>
<style>
:root {{ --bg:#fff; --fg:#1a1f2e; --muted:#5b6475; --line:#d9dee7; --head:#f2f4f8; --accent:#b45309; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#11151f; --fg:#e6e9ef; --muted:#9aa3b2; --line:#2a3142; --head:#1a2030; --accent:#f8b304; }} }}
body {{ background:var(--bg); color:var(--fg); font:15px/1.5 system-ui, sans-serif; max-width:960px; margin:0 auto; padding:24px 16px; }}
h1 {{ margin:0 0 4px; }} .meta {{ color:var(--muted); }} .big {{ font-size:22px; color:var(--accent); font-weight:600; }}
table {{ border-collapse:collapse; width:100%; margin:8px 0 24px; }} th, td {{ border-bottom:1px solid var(--line); padding:6px 8px; text-align:left; }}
th {{ background:var(--head); }} td:not(:first-child), th:not(:first-child) {{ text-align:right; }}
details {{ border:1px solid var(--line); border-radius:6px; padding:8px 12px; margin:8px 0; }} summary {{ cursor:pointer; }}
.a {{ color:var(--muted); }}
</style></head><body>
<h1>ShopKart Copilot: eval report</h1>
<p class=meta>{e(d['date'])} · {d['cases']} cases · Copilot {e(d['model'])}, prompt {e(str(d['prompt']))} · judge {e(d['judge'])} on {d['judged']} cases</p>
<p>Overall pass rate: <span class=big>{e(d['overall'])}</span></p>
<h2>By category</h2>
{table(["Category", "Cases", "Code checks", "Judge", "Overall"], [[c["category"], c["cases"], c["code"], c["judge"], c["overall"]] for c in d["by_cat"]])}
<h2>By check</h2>
{table(["Check", "Applies to", "Pass", "Fail"], [[c["check"], c["applies"], c["pass"], c["fail"]] for c in d["by_check"]])}
<h2>Failures ({len(d['failures'])})</h2>
{fails}
<p class=meta>New spend for this run: ${d['cost']:.6f} (cached answers cost $0).</p>
</body></html>
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Write the eval score report (markdown and HTML).")
    p.add_argument("--results", type=Path, default=None, help="default: out/judged.jsonl, else out/results.jsonl")
    p.add_argument("--out", type=Path, default=OUT)
    args = p.parse_args(argv)
    src = args.results or (OUT / "judged.jsonl" if (OUT / "judged.jsonl").exists() else OUT / "results.jsonl")
    d = build(read_jsonl(src))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.md").write_text(to_markdown(d), encoding="utf-8")
    (args.out / "report.html").write_text(to_html(d), encoding="utf-8")
    print(f"{d['cases']} cases from {src.name} · overall pass rate {d['overall']}\n")
    print(f"{'category':<14} {'cases':>5}  {'code checks':<13} {'judge':<13} overall")
    for c in d["by_cat"]:
        print(f"{c['category']:<14} {c['cases']:>5}  {c['code']:<13} {c['judge']:<13} {c['overall']}")
    print(f"\n{len(d['failures'])} failures listed · wrote out/report.md and out/report.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
