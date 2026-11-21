"""The load-test lab's tester, with policy questions instead of order questions.

    uv run python capstone/production/solution/loadtest_docs.py $URL --requests 60 --concurrency 5 --users 60

Point it at the app in FAKE mode (LLM_PROVIDER=fake): real search and checks, no model, no cost.
A few "I don't know" questions are mixed in, so the floor's no-call path is load-tested too.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "labs" / "loadtest" / "done"))

import loadtest  # noqa: E402

GOLDEN = ROOT / "data" / "golden" / "rag-50.jsonl"
IDK = ROOT / "capstone" / "doc-assistant" / "solution" / "idk-10.jsonl"


def questions() -> list[str]:
    rag = [json.loads(line)["question"] for line in GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]
    idk = [json.loads(line)["question"] for line in IDK.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rag[:20] + idk[:5]  # 4 in 5 answerable, like real traffic is (we hope)


loadtest.QUESTIONS[:] = questions()

if __name__ == "__main__":
    sys.exit(loadtest.main())
