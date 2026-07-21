from __future__ import annotations

from kol_indices import build_daily_index, direction, match_asset_keys


def _payload(*tweets):
    return {"sections": [{"key": "commodities", "tweets": list(tweets)}]}


def _tweet(handle, body, tier=2, engagement=100):
    return {"handle": handle, "body": body, "tier": tier, "engagement": engagement}


def test_asset_matching_keeps_softs_separate_from_grains():
    assert match_asset_keys("Coffee and cocoa supply is tight") == ["softs"]
    assert match_asset_keys("Corn and soybean crop outlook") == ["grains"]
    assert "softs" not in match_asset_keys("A rubber stamp for the proposal")


def test_direction_handles_compound_and_negated_phrases():
    assert direction("Brent short covering rally has more upside") == 1
    assert direction("Investors trimmed bearish shorts and established new bullish longs") == 1
    assert direction("A closure would reduce global oil supply") == 1
    assert direction("Coffee is not bullish and demand is weak") == -1
    assert direction("Cotton may trade in a range") == 0
    assert direction("Short-term oil prices may be supported") == 1


def test_daily_index_is_null_without_direction_and_weighted_with_signal():
    payload = _payload(
        _tweet("A", "Coffee may trade in a range", engagement=20),
        _tweet("B", "Coffee supply is tight and the breakout looks bullish", tier=1, engagement=500),
        _tweet("C", "Coffee demand is weak and prices may break lower", tier=3, engagement=10),
    )
    result = build_daily_index(payload, "2026-07-20")["assets"]["softs"]
    assert result["mentions"] == 3
    assert result["signal_tweets"] == 2
    assert result["bullish"] == 1 and result["bearish"] == 1
    assert result["score"] > 0

    neutral = build_daily_index(
        _payload(_tweet("A", "Cotton may trade in a range")), "2026-07-20"
    )["assets"]["softs"]
    assert neutral["score"] is None
