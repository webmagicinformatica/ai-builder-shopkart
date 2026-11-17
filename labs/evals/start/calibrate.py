"""Part 2: check the judge against people before you trust it.

The support lead labels 10 answers pass or fail with the same rubric. We compare:
agreement, how many of HER failures the judge caught, and its false alarms.

    uv run python labs/evals/done/calibrate.py --template     # pick 10 answers to label
    uv run python labs/evals/done/calibrate.py                # compare with the judge
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from cases import LAB, read_jsonl

LABELS = LAB / "hand_labels.jsonl"
JUDGED = LAB / "out" / "judged.jsonl"


def pick_for_labelling(rows: list[dict[str, Any]], n: int = 10) -> list[dict[str, Any]]:
    """n judged answers, spread evenly over the file (so every category shows up)."""
    judged = [r for r in rows if r.get("judge") and "verdict" in r["judge"]]
    if len(judged) <= n:
        return judged
    step = len(judged) / n
    return [judged[int(i * step)] for i in range(n)]


def compare(labels: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {r["id"]: r for r in rows}
    pairs, stale, missing = [], [], []
    for lab in labels:
        row = by_id.get(lab["id"])
        if not row or not row.get("judge") or "verdict" not in row["judge"]:
            missing.append(lab["id"])
            continue
        if lab.get("reply") and lab["reply"] != row.get("reply"):
            stale.append(lab["id"])  # the answer changed since it was labelled
        pairs.append((lab["id"], lab["label"], row["judge"]["verdict"], row["judge"]["reason"]))

    n = len(pairs)
    # TODO 7: the calibration numbers. Each pair is (id, human, judge, reason).
    #   agree:        cases where human and judge give the same verdict
    #   human_fails:  the pairs the human failed
    #   caught:       of those, how many the judge failed too
    #   false_alarms: good answers (human pass) the judge failed
    #   lazy:         how often a judge that passes everything would agree (count of human passes)
    raise NotImplementedError("TODO 7: calibration numbers")
    return {"pairs": pairs, "n": n, "agree": agree, "human_fails": len(human_fails), "caught": caught,
            "false_alarms": false_alarms, "lazy_agree": lazy, "stale": stale, "missing": missing}


def show(c: dict[str, Any]) -> str:
    if not c["n"]:
        return "No labelled answer has a judge verdict yet: run judge.py first."
    pct = lambda a, b: f"{a / b:.0%}" if b else "n/a"  # noqa: E731
    lines = [f"{'case':<7} {'human':<6} {'judge':<6}", "-" * 60]
    for cid, h, j, reason in c["pairs"]:
        tag = "" if h == j else ("  MISSED a failure" if h == "fail" else "  false alarm")
        lines.append(f"{cid:<7} {h:<6} {j:<6}{tag}")
        if h != j:
            lines.append(f"        judge said: {reason}")
    lines += [
        "",
        f"agreement:             {c['agree']}/{c['n']} ({pct(c['agree'], c['n'])})",
        f"human failures caught: {c['caught']}/{c['human_fails']} ({pct(c['caught'], c['human_fails'])})",
        f"false alarms:          {c['false_alarms']} (good answers the judge failed)",
        f"a lazy judge that passes everything would agree {c['lazy_agree']}/{c['n']} "
        f"({pct(c['lazy_agree'], c['n'])})",
    ]
    if c["stale"]:
        lines.append(f"WARNING: answers changed since labelling: {', '.join(c['stale'])}. Label them again.")
    if c["missing"]:
        lines.append(f"not judged yet: {', '.join(c['missing'])}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Compare the judge with hand labels.")
    p.add_argument("--judged", type=Path, default=JUDGED)
    p.add_argument("--labels", type=Path, default=LABELS)
    p.add_argument("--template", action="store_true", help="write 10 answers to label, then stop")
    args = p.parse_args(argv)

    rows = read_jsonl(args.judged)
    if args.template:
        if args.labels.exists():
            print(f"{args.labels.name} already exists; delete it first to start again.", file=sys.stderr)
            return 1
        picked = pick_for_labelling(rows)
        args.labels.write_text("".join(json.dumps(
            {"id": r["id"], "label": "?", "note": "", "question": r["question"], "reply": r["reply"],
             "handover": r["handover"]}, ensure_ascii=False) + "\n" for r in picked), encoding="utf-8")
        print(f"wrote {len(picked)} answers to {args.labels.name}. Read each one with the rubric in judge.py "
              "and set label to pass or fail. Don't look at the judge's verdict first.")
        return 0

    labels = read_jsonl(args.labels)
    todo = [lab["id"] for lab in labels if lab["label"] not in ("pass", "fail")]
    if todo:
        print(f"label these first (pass or fail): {', '.join(todo)}", file=sys.stderr)
        return 1
    print(f"{len(labels)} hand labels vs the judge\n")
    print(show(compare(labels, rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
