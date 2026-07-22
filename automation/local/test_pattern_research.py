import pandas as pd

from pattern_research import enrich_pattern, market_context, walk_forward_backtest


def frame(n=320):
    close = [100 + i * 0.1 for i in range(n)]
    data = pd.DataFrame(
        {
            "open": [value - 0.05 for value in close],
            "high": [value + 0.2 for value in close],
            "low": [value - 0.2 for value in close],
            "close": close,
            "volume": [100.0] * n,
            "hold": [1000.0 + i for i in range(n)],
        },
    )
    data.index = pd.date_range("2026-01-01", periods=n, freq="h")
    return data


def test_market_context_uses_observable_trend_and_participation():
    context = market_context(frame())
    assert context["trend"] == "bullish"
    assert context["volume_ratio"] == 1.0
    assert context["oi_change"] > 0


def test_stale_geometry_never_becomes_a_decision_signal():
    context = market_context(frame())
    result = enrich_pattern(
        {
            "bias": "bullish",
            "last_close": 105,
            "trigger": 104,
            "target": 108,
            "stop": 102,
            "bars_since": 80,
            "triggered": True,
            "exhausted": False,
        },
        context,
    )
    assert result["trade_state"] == "stale"
    assert result["decision_eligible"] is False


def test_walk_forward_uses_future_crossing_and_directional_return():
    df = frame()

    def detector(history):
        if len(history) != 220:
            return []
        return [{"confidence": 0.8, "start_bar": 200, "end_bar": 219}]

    def levels(hit, history):
        return {
            **hit,
            "pattern": "Rectangle",
            "bias": "bullish",
            "trigger": float(history["close"].iloc[-1]) + 0.05,
        }

    result = walk_forward_backtest(df, detector, levels, step=1)
    assert result["samples"] == 1
    assert result["horizons"]["8"]["win_rate"] == 1.0
    assert result["horizons"]["24"]["avg_return"] > 0
