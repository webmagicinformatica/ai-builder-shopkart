"""ShopKart's first cost-tracked call, on OpenAI.

Run:  uv run hello_openai.py
"""

import sys

import openai

from shopkart import budget
from shopkart.console import check_budget_or_exit, print_call, print_today, require_key
from shopkart.pricing import cost_usd

MODEL = "gpt-6-luna"
PROMPT = "Greet a ShopKart customer in one short sentence."


def main() -> None:
    api_key = require_key("OPENAI_API_KEY")

    # 1. Budget check BEFORE the call.
    check_budget_or_exit()

    # 2. One small call.
    client = openai.OpenAI(api_key=api_key)
    try:
        response = client.responses.create(
            model=MODEL,
            input=PROMPT,
            max_output_tokens=100,
            reasoning={"effort": "none"},  # a greeting needs no reasoning
        )
    except openai.AuthenticationError:
        sys.exit("OpenAI rejected the key. Check the OPENAI_API_KEY secret.")
    except openai.APIError as exc:
        sys.exit(f"OpenAI API error: {exc}")

    reply = response.output_text.strip()
    tokens_in = response.usage.input_tokens
    tokens_out = response.usage.output_tokens

    # 3. Cost of this call, in $ and ₹.
    cost = cost_usd(MODEL, tokens_in, tokens_out)
    print_call(MODEL, reply, tokens_in, tokens_out, cost)

    # 4. Record the spend AFTER the call.
    print_today(budget.record(cost))


if __name__ == "__main__":
    main()
