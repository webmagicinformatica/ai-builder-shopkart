import pytest

from shopkart.pricing import PRICES_PER_MILLION_USD, USD_TO_INR, cost_usd, usd_to_inr


def test_small_model_cost():
    # 1,000 in at $0.10/M + 200 out at $0.50/M = $0.0001 + $0.0001
    assert cost_usd("claude-haiku-5-5", 1_000, 200) == pytest.approx(0.0002)
    assert cost_usd("gpt-6-luna", 1_000, 200) == pytest.approx(0.0002)


def test_output_tokens_cost_five_times_more():
    for price_in, price_out in PRICES_PER_MILLION_USD.values():
        assert price_out == pytest.approx(5 * price_in)


def test_zero_tokens_cost_nothing():
    assert cost_usd("claude-haiku-5-5", 0, 0) == 0


def test_unknown_model_is_an_error():
    with pytest.raises(KeyError):
        cost_usd("some-new-model", 10, 10)


def test_rupees():
    assert usd_to_inr(1.0) == pytest.approx(USD_TO_INR)
    assert usd_to_inr(0.002) == pytest.approx(0.002 * USD_TO_INR)
