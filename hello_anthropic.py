"""ShopKart's first cost-tracked call, on Anthropic (Claude).

Run:  uv run hello_anthropic.py
"""

import sys

import anthropic

from shopkart import budget
from shopkart.console import check_budget_or_exit, print_call, print_today, require_key
from shopkart.pricing import cost_usd

MODEL = "claude-haiku-5-5"
PROMPT = "Greet a ShopKart customer in one short sentence."


def main() -> None:
    api_key = require_key("ANTHROPIC_API_KEY")

    # 1. Budget check BEFORE the call.
    check_budget_or_exit()

    # 2. One small call.
    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=100,
            thinking={"type": "disabled"},  # a greeting needs no thinking
            messages=[{"role": "user", "content": PROMPT}],
        )
    except anthropic.AuthenticationError:
        sys.exit("Anthropic rejected the key. Check the ANTHROPIC_API_KEY secret.")
    except anthropic.APIError as exc:
        sys.exit(f"Anthropic API error: {exc}")

    reply = "".join(block.text for block in response.content if block.type == "text").strip()
    tokens_in = response.usage.input_tokens
    tokens_out = response.usage.output_tokens

    # 3. Cost of this call, in $ and ₹.
    cost = cost_usd(MODEL, tokens_in, tokens_out)
    print_call(MODEL, reply, tokens_in, tokens_out, cost)

    # 4. Record the spend AFTER the call.
    print_today(budget.record(cost))


if __name__ == "__main__":
    main()
