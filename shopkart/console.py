"""Small helpers the hello scripts share: reading keys and printing a call."""

import os
import sys

from dotenv import load_dotenv

from shopkart import budget
from shopkart.pricing import usd_to_inr

# Codespaces secrets arrive as environment variables. A .env file is only a
# fallback for running outside Codespaces; it never overrides a real secret.
load_dotenv(override=False)


def require_key(env_name: str) -> str:
    """Return the API key from the environment, or exit with a friendly hint."""
    key = os.environ.get(env_name, "").strip()
    if key:
        return key
    print(
        f"""
{env_name} is not set, so no call was made.

In GitHub Codespaces (recommended):
  1. github.com -> Settings -> Codespaces -> Secrets -> New secret
  2. Name: {env_name}   Value: your API key
  3. Under "Repository access", pick this repository, then save.
  4. Reload the codespace when VS Code offers it (or stop and start it).

Running outside Codespaces? Copy .env.example to .env and fill in {env_name}.
""",
        file=sys.stderr,
    )
    sys.exit(1)


def check_budget_or_exit() -> None:
    """Run the budget check; on BudgetExceeded print why and exit non-zero."""
    try:
        budget.check()
    except budget.BudgetExceeded as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)


def print_call(model: str, reply: str, input_tokens: int, output_tokens: int, cost: float) -> None:
    """Print one call as a clean block: model, reply, tokens and cost."""
    print(
        f"""
Model:   {model}
Reply:   {reply}
Tokens:  {input_tokens} in, {output_tokens} out
Cost:    ${cost:.6f}  (₹{usd_to_inr(cost):.2f})
"""
    )


def print_today(total: float) -> None:
    print(f"Today:   ${total:.6f} of ${budget.daily_budget_usd():.2f} daily budget")
