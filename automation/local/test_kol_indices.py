from __future__ import annotations

from kol_indices import build_daily_index, build_daily_index_from_digest, direction, match_asset_keys


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
    assert result["score"] < result["raw_score"]
    assert result["confidence"] == 0.4

    neutral = build_daily_index(
        _payload(_tweet("A", "Cotton may trade in a range")), "2026-07-20"
    )["assets"]["softs"]
    assert neutral["score"] is None


def test_structured_view_uses_trading_implication_and_shrinks_small_samples():
    payload = {"sections": [{"kol_blocks": [{
        "handle": "EnergyA", "tier": 1, "top_engagement": 100,
        "views": [{
            "view": "美国石油钻机数量上升。",
            "insight": "若产量上升兑现，油价上行空间将受限。",
        }],
    }, {
        "handle": "GoldA", "tier": 1, "top_engagement": 100,
        "views": [{
            "view": "美元可能大幅贬值，黄金将受益。",
            "insight": "黄金长期重估。",
        }],
    }]}]}
    result = build_daily_index_from_digest(payload, "2026-07-21")
    assert result["source"] == "structured_views"
    assert result["assets"]["energy"]["score"] == -25.0
    assert result["assets"]["metals"]["score"] == 25.0
