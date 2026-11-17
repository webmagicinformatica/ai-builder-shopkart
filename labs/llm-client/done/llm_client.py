"""The finished LLM client is shopkart/llm.py: every later lab imports it from there.

This file only re-exports it, so the lab's scripts and tests can say
`from llm_client import LLM` in start/ and done/ alike.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # the repo root, where shopkart/ lives

from shopkart.llm import (  # noqa: E402, F401
    LLM,
    LLMError,
    Result,
    SchemaError,
    SpendLimitReached,
    StreamInterrupted,
    Verdict,
    classify,
    main,
)

if __name__ == "__main__":
    sys.exit(main())
