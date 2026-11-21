"""Draw the CloudWatch dashboard's charts as PNG files, and print its two tables. No console needed.

    uv run python labs/tracing/done/dashboard_png.py $LOG --minutes 30

Charts go to .shopkart/dashboard/*.png (open them in VS Code). The tables are the dashboard's
Logs Insights queries: the slowest requests (with their trace IDs) and cost by prompt version.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import boto3

LAB = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parents[3] / ".shopkart" / "dashboard"


def charts(minutes: int) -> list[Path]:
    cw = boto3.client("cloudwatch")
    OUT.mkdir(parents=True, exist_ok=True)
    files = []
    for i, w in enumerate(json.loads((LAB / "dashboard.json").read_text())["widgets"]):
        if w["type"] != "metric":
            continue
        props = {k: v for k, v in w["properties"].items() if k != "region"}
        props.update(start=f"-PT{minutes}M", width=900, height=320)
        png = cw.get_metric_widget_image(MetricWidget=json.dumps(props))["MetricWidgetImage"]
        path = OUT / f"{i + 1}-{props['title'].split(':')[0].split('(')[0].strip().lower().replace(' ', '-')}.png"
        path.write_bytes(png)
        files.append(path)
    return files


def tables(log_group: str, minutes: int) -> None:
    logs = boto3.client("logs")
    for w in json.loads((LAB / "dashboard.json").read_text())["widgets"]:
        if w["type"] != "log":
            continue
        query = w["properties"]["query"].split("|", 1)[1]  # drop "SOURCE '...'"
        qid = logs.start_query(logGroupName=log_group, startTime=int(time.time()) - minutes * 60,
                               endTime=int(time.time()), queryString=query)["queryId"]
        while (res := logs.get_query_results(queryId=qid))["status"] in ("Scheduled", "Running"):
            time.sleep(1)
        print(f"\n{w['properties']['title']}")
        rows = [{f["field"]: f["value"] for f in row if f["field"] != "@ptr"} for row in res["results"]]
        if not rows:
            print("  (no rows yet: metrics and logs can take a minute or two)")
            continue
        cols = list(rows[0])
        width = {c: max(len(c), *(len(r.get(c, "")) for r in rows)) for c in cols}
        print("  " + "  ".join(c.ljust(width[c]) for c in cols))
        for r in rows:
            print("  " + "  ".join(r.get(c, "").ljust(width[c]) for c in cols))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="The ShopKart dashboard, in the terminal")
    p.add_argument("log_group", help="the service's log group, e.g. /aws/ecs/shopkart/shopkart-copilot-xxxx")
    p.add_argument("--minutes", type=int, default=30)
    args = p.parse_args(argv)
    for path in charts(args.minutes):
        print(f"chart: {path.relative_to(OUT.parents[1])}")
    tables(args.log_group, args.minutes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
