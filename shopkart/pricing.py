"""What one API call costs, in dollars and rupees.

Providers bill per token, quoted as a price per MILLION tokens, with separate
prices for input (your prompt) and output (the model's answer).

Prices change, so check the current pricing page before you trust a number:
  Anthropic: https://platform.claude.com/docs/en/about-claude/pricing
  OpenAI:    https://developers.openai.com/api/docs/pricing
"""

# US dollars per 1,000,000 tokens: (input, output). Checked November 2026.
PRICES_PER_MILLION_USD: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),  # Anthropic: small, fast Claude model
    "gpt-6-luna": (0.10, 0.50),        # OpenAI: small, efficient model
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
