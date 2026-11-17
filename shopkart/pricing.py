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
    "claude-sonnet-5-5": (2.00, 10.00),  # Anthropic: large model (cost lab)
    "gpt-6.2-sol": (2.00, 10.00),        # OpenAI: large model (cost lab)
}

# Prompt caching. A cache read ("cache hit", OpenAI's "cached input") costs a
# fraction of the input price, and the fraction differs by model. A cache
# write on Claude (5-minute cache) costs 1.25x the input price; OpenAI charges
# nothing extra to write. Checked November 2026.
CACHE_READ_FACTOR: dict[str, float] = {
    "claude-haiku-5-5": 0.10,   # $0.01 per million
    "claude-sonnet-5-5": 0.05,  # $0.10 per million
    "gpt-6-luna": 0.10,         # $0.01 per million
    "gpt-6.2-sol": 0.05,        # $0.10 per million
}
DEFAULT_CACHE_READ_FACTOR = 0.10
CACHE_WRITE_FACTOR = 1.25

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


def cache_cost_usd(model: str, cache_read_tokens: int, cache_write_tokens: int = 0) -> float:
    """Cost of the cached part of a prompt: reads at a discount, writes at a premium."""
    price_in = PRICES_PER_MILLION_USD[model][0]
    read = CACHE_READ_FACTOR.get(model, DEFAULT_CACHE_READ_FACTOR)
    return (cache_read_tokens * read + cache_write_tokens * CACHE_WRITE_FACTOR) * price_in / 1_000_000


def usd_to_inr(usd: float) -> float:
    """Convert dollars to rupees with USD_TO_INR."""
    return usd * USD_TO_INR
