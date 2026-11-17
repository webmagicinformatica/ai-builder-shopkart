"""What one API call costs, in dollars and rupees.

Providers bill per token, quoted as a price per MILLION tokens, with separate
prices for input (your prompt) and output (the model's answer).

These are the course's EXAMPLE prices, not live ones. Real prices change
(and today's small models are often cheaper than this), so always check the
current pricing page before you trust a number:
  Anthropic: https://platform.claude.com/docs/en/about-claude/pricing
  OpenAI:    https://developers.openai.com/api/docs/pricing
"""

# Example prices in US dollars per 1,000,000 tokens: (input, output).
SMALL_MODEL = (1.00, 5.00)
LARGE_MODEL = (3.00, 15.00)

# Real model IDs we use in the labs, mapped to the example tiers above.
PRICES_PER_MILLION_USD: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-haiku-5-5": SMALL_MODEL,   # small, fast Claude model
    "claude-sonnet-5-5": LARGE_MODEL,  # larger Claude model (used in later lessons)
    # OpenAI
    "gpt-6-luna": SMALL_MODEL,         # small, efficient OpenAI model
    "gpt-6.2-sol": LARGE_MODEL,        # larger OpenAI model (used in later lessons)
}

# Rupees per US dollar. An approximate rate, fine for estimates: your bank
# may use a different rate and add a forex fee. Update it when it drifts.
USD_TO_INR = 88.0


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Cost of one call in US dollars."""
    if model not in PRICES_PER_MILLION_USD:
        raise KeyError(
            f"No price for model {model!r}. Add it to PRICES_PER_MILLION_USD "
            "in shopkart/pricing.py."
        )
    price_in, price_out = PRICES_PER_MILLION_USD[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def usd_to_inr(usd: float) -> float:
    """Convert dollars to rupees with USD_TO_INR."""
    return usd * USD_TO_INR
