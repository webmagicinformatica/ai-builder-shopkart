"""Print one trace from Jaeger as a tree, with each span's time and its gen-AI attributes.

    uv run python labs/tracing/done/show_trace.py <trace_id>

The trace ID is in the done event, and in the X-Trace-ID response header.
The same trace is in the Jaeger UI (port 16686): search for service shopkart-copilot.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

JAEGER = os.environ.get("JAEGER_URL", "http://localhost:16686")
SHOW = ("gen_ai.", "shopkart.", "error.type")


def fetch(trace_id: str) -> list[dict]:
    with urllib.request.urlopen(f"{JAEGER}/api/traces/{trace_id}", timeout=10) as r:
        return json.load(r)["data"][0]["spans"]


def render(spans: list[dict]) -> list[str]:
    by_id = {s["spanID"]: s for s in spans}
    children: dict[str | None, list[dict]] = {}
    for s in spans:
        parent = next((r["spanID"] for r in s.get("references", []) if r["refType"] == "CHILD_OF"), None)
        children.setdefault(parent if parent in by_id else None, []).append(s)
    lines: list[str] = []
    t0 = min(s["startTime"] for s in spans)

    def walk(span: dict, prefix: str, last: bool, top: bool) -> None:
        branch = "" if top else ("└─ " if last else "├─ ")
        start_ms = (span["startTime"] - t0) / 1000
        lines.append(f"{prefix}{branch}{span['operationName']:<34} {span['duration'] / 1000:>8.0f} ms"
                     f"   (starts at {start_ms:.0f} ms)")
        pad = prefix + ("" if top else ("   " if last else "│  "))
        for log in span.get("logs", []):
            name = next((f["value"] for f in log["fields"] if f["key"] == "event"), "event")
            lines.append(f"{pad}   · {name} at {(log['timestamp'] - t0) / 1000:.0f} ms")
        for tag in span["tags"]:
            if tag["key"].startswith(SHOW):
                value = " ".join(str(tag["value"]).split())  # one line
                value = value if len(value) <= 90 else "..." + value[-87:]  # the end is the interesting part
                lines.append(f"{pad}     {tag['key']} = {value}")
        kids = sorted(children.get(span["spanID"], []), key=lambda s: s["startTime"])
        for i, kid in enumerate(kids):
            walk(kid, pad, i == len(kids) - 1, False)

    for root in children.get(None, []):
        walk(root, "", True, True)
    return lines


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    print(f"Trace {argv[0]}")
    print("\n".join(render(fetch(argv[0]))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
