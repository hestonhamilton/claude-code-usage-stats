import json

from cus.pricing import load_prices, cost_for


def test_cost_for_known_opus_with_both_ephemeral_buckets():
    prices = load_prices()

    cost = cost_for(
        "claude-opus-4-8",
        input_tokens=100,
        output_tokens=10,
        ephemeral_5m_tokens=20,
        ephemeral_1h_tokens=30,
        cache_read_tokens=40,
        cache_creation_tokens=50,
        prices=prices,
    )

    expected = (
        100 * 0.000005
        + 10 * 0.000025
        + 20 * 0.000005 * 1.25
        + 30 * 0.000005 * 2.0
        + 40 * 0.000005 * 0.10
    )
    assert cost == expected


def test_cost_for_falls_back_to_5m_cache_write_when_split_absent():
    prices = load_prices()

    cost = cost_for(
        "claude-opus-4-8",
        input_tokens=0,
        output_tokens=0,
        ephemeral_5m_tokens=0,
        ephemeral_1h_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=12,
        prices=prices,
    )

    assert cost == 12 * 0.000005 * 1.25


def test_cost_for_cache_read_heavy_event():
    prices = load_prices()

    cost = cost_for(
        "claude-sonnet-4-6",
        input_tokens=1,
        output_tokens=1,
        ephemeral_5m_tokens=0,
        ephemeral_1h_tokens=0,
        cache_read_tokens=10_000,
        cache_creation_tokens=0,
        prices=prices,
    )

    expected = 1 * 0.000003 + 1 * 0.000015 + 10_000 * 0.000003 * 0.10
    assert cost == expected


def test_cost_for_unknown_model_returns_none():
    prices = load_prices()

    assert cost_for("<synthetic>", 1, 1, 1, 1, 1, 2, prices) is None
    assert cost_for("claude-made-up", 1, 1, 1, 1, 1, 2, prices) is None


def test_cost_for_strips_dated_model_suffix_to_match_canonical_id():
    prices = load_prices()

    dated = cost_for(
        "claude-haiku-4-5-20251001",
        input_tokens=100,
        output_tokens=10,
        ephemeral_5m_tokens=0,
        ephemeral_1h_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        prices=prices,
    )
    canonical = cost_for(
        "claude-haiku-4-5",
        input_tokens=100,
        output_tokens=10,
        ephemeral_5m_tokens=0,
        ephemeral_1h_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        prices=prices,
    )

    assert dated == canonical
    assert dated is not None

    # <synthetic> and genuinely-unknown ids stay unpriced even after normalization.
    assert cost_for("<synthetic>", 1, 1, 0, 0, 0, 0, prices) is None
    assert cost_for("claude-made-up-20251001", 1, 1, 0, 0, 0, 0, prices) is None


def test_cost_for_strips_anthropic_prefix_and_date_suffix_together():
    prices = load_prices()

    cost = cost_for(
        "anthropic/claude-haiku-4-5-20251001",
        input_tokens=100,
        output_tokens=10,
        ephemeral_5m_tokens=0,
        ephemeral_1h_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        prices=prices,
    )

    assert cost is not None
    assert cost == 100 * 0.000001 + 10 * 0.000005


def test_load_prices_litellm_fixture_overrides_and_strips_anthropic_prefix(tmp_path):
    fixture = tmp_path / "model_prices_and_context_window.json"
    fixture.write_text(
        json.dumps(
            {
                "claude-opus-4-8": {
                    "input_cost_per_token": 0.001,
                    "output_cost_per_token": 0.002,
                },
                "anthropic/claude-x": {
                    "input_cost_per_token": 0.003,
                    "output_cost_per_token": 0.004,
                },
            }
        ),
        encoding="utf-8",
    )

    prices = load_prices(fixture)

    assert prices["claude-opus-4-8"]["input_cost_per_token"] == 0.001
    assert prices["claude-opus-4-8"]["output_cost_per_token"] == 0.002
    assert prices["claude-x"]["input_cost_per_token"] == 0.003
    assert prices["claude-x"]["output_cost_per_token"] == 0.004


def test_load_prices_litellm_override_with_dated_id_matches_canonical_key(tmp_path):
    fixture = tmp_path / "model_prices_and_context_window.json"
    fixture.write_text(
        json.dumps(
            {
                "anthropic/claude-haiku-4-5-20251001": {
                    "input_cost_per_token": 0.0009,
                    "output_cost_per_token": 0.0044,
                },
            }
        ),
        encoding="utf-8",
    )

    prices = load_prices(fixture)

    # Both prefix and date suffix stripped when the override key is stored,
    # so lookups against the canonical (undated) model id resolve.
    assert prices["claude-haiku-4-5"]["input_cost_per_token"] == 0.0009
    assert prices["claude-haiku-4-5"]["output_cost_per_token"] == 0.0044

    cost = cost_for(
        "claude-haiku-4-5-20251001",
        input_tokens=100,
        output_tokens=10,
        ephemeral_5m_tokens=0,
        ephemeral_1h_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        prices=prices,
    )
    assert cost == 100 * 0.0009 + 10 * 0.0044
