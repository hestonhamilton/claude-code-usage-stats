from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path


CACHE_WRITE_5M_MULTIPLIER = 1.25
CACHE_WRITE_1H_MULTIPLIER = 2.00
CACHE_READ_MULTIPLIER = 0.10

_PER_MILLION = 1_000_000

# Claude Code sometimes reports dated model ids (e.g.
# "claude-haiku-4-5-20251001"); strip the trailing release date so pricing
# still resolves against the canonical model id.
_DATE_SUFFIX_RE = re.compile(r"-\d{8}$")

DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "claude-opus-4-8": {
        "input_cost_per_token": 5 / _PER_MILLION,
        "output_cost_per_token": 25 / _PER_MILLION,
    },
    "claude-opus-4-7": {
        "input_cost_per_token": 5 / _PER_MILLION,
        "output_cost_per_token": 25 / _PER_MILLION,
    },
    "claude-opus-4-6": {
        "input_cost_per_token": 5 / _PER_MILLION,
        "output_cost_per_token": 25 / _PER_MILLION,
    },
    "claude-sonnet-5": {
        "input_cost_per_token": 3 / _PER_MILLION,
        "output_cost_per_token": 15 / _PER_MILLION,
    },
    "claude-sonnet-4-6": {
        "input_cost_per_token": 3 / _PER_MILLION,
        "output_cost_per_token": 15 / _PER_MILLION,
    },
    "claude-haiku-4-5": {
        "input_cost_per_token": 1 / _PER_MILLION,
        "output_cost_per_token": 5 / _PER_MILLION,
    },
    "claude-fable-5": {
        "input_cost_per_token": 10 / _PER_MILLION,
        "output_cost_per_token": 50 / _PER_MILLION,
    },
}


def _bare_model_id(model: str) -> str:
    if model.startswith("anthropic/"):
        return model.removeprefix("anthropic/")
    return model


def _strip_date_suffix(model: str) -> str:
    return _DATE_SUFFIX_RE.sub("", model)


def _normalize_model_id(model: str) -> str:
    return _strip_date_suffix(_bare_model_id(model))


def _model_id_candidates(model: str) -> list[str]:
    """Ordered, deduped lookup candidates: exact, anthropic-stripped,
    date-stripped, both stripped."""
    anthropic_stripped = _bare_model_id(model)
    date_stripped = _strip_date_suffix(model)
    both_stripped = _normalize_model_id(model)
    candidates = [model, anthropic_stripped, date_stripped, both_stripped]
    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            ordered.append(candidate)
    return ordered


def load_prices(path: str | Path | None = None) -> dict[str, dict[str, float]]:
    prices = {model: rates.copy() for model, rates in DEFAULT_PRICES.items()}
    if path is None:
        return prices

    with Path(path).open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return prices

    for model, raw_rates in data.items():
        if not isinstance(model, str) or not isinstance(raw_rates, dict):
            continue
        input_rate = raw_rates.get("input_cost_per_token")
        output_rate = raw_rates.get("output_cost_per_token")
        if not isinstance(input_rate, int | float) or not isinstance(output_rate, int | float):
            continue
        prices[_normalize_model_id(model)] = {
            "input_cost_per_token": float(input_rate),
            "output_cost_per_token": float(output_rate),
        }
    return prices


def cost_for(
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    ephemeral_5m_tokens: int,
    ephemeral_1h_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    prices: dict[str, dict[str, float]],
) -> float | None:
    if model is None:
        return None
    rates = None
    for candidate in _model_id_candidates(model):
        rates = prices.get(candidate)
        if rates is not None:
            break
    if rates is None:
        return None

    input_rate = rates["input_cost_per_token"]
    output_rate = rates["output_cost_per_token"]
    unattributed_cache_write_tokens = 0
    if ephemeral_5m_tokens == 0 and ephemeral_1h_tokens == 0 and cache_creation_tokens > 0:
        unattributed_cache_write_tokens = max(
            0,
            cache_creation_tokens - ephemeral_1h_tokens - ephemeral_5m_tokens,
        )

    return (
        input_tokens * input_rate
        + output_tokens * output_rate
        + (ephemeral_5m_tokens + unattributed_cache_write_tokens)
        * input_rate
        * CACHE_WRITE_5M_MULTIPLIER
        + ephemeral_1h_tokens * input_rate * CACHE_WRITE_1H_MULTIPLIER
        + cache_read_tokens * input_rate * CACHE_READ_MULTIPLIER
    )


def fetch_litellm(url: str, dest_path: str | Path) -> None:
    with urllib.request.urlopen(url) as response:
        data = response.read()
    Path(dest_path).write_bytes(data)
