"""Model pricing table and cost computation.

Prices are USD per 1M tokens (input, output). Update as providers change pricing;
unknown models simply get cost_usd=None rather than a wrong number.
"""

from __future__ import annotations

from typing import Optional, Tuple

# (input_per_1m, output_per_1m) in USD
PRICING: dict[str, Tuple[float, float]] = {
    # Anthropic
    "claude-fable-5-2": (20.0, 100.0),
    "claude-fable-5": (20.0, 100.0),
    "claude-opus-5-5": (5.0, 25.0),
    "claude-sonnet-5-5": (3.0, 15.0),
    "claude-haiku-5-5": (1.0, 5.0),
    "claude-opus-4-1": (15.0, 75.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    # OpenAI (common ids)
    "gpt-5": (10.0, 30.0),
    "gpt-5-mini": (2.0, 8.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
}


def _lookup(model: str) -> Optional[Tuple[float, float]]:
    if model in PRICING:
        return PRICING[model]
    # Tolerate dated/prefixed ids like "claude-sonnet-5-5-20260101" or "us.anthropic.claude-...".
    for known, price in PRICING.items():
        if known in model:
            return price
    return None


def compute_cost(model: Optional[str], input_tokens: Optional[int], output_tokens: Optional[int]) -> Optional[float]:
    if not model:
        return None
    price = _lookup(model)
    if price is None:
        return None
    cost = ((input_tokens or 0) * price[0] + (output_tokens or 0) * price[1]) / 1_000_000
    return round(cost, 8)
