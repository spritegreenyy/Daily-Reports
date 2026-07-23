import pandas as pd

from pattern_research import enrich_pattern, market_context, technical_snapshot, walk_forward_backtest
from hourly_pattern_report import (
    aggregate_backtests,
    apply_evidence_framework,
    apply_portfolio_gate,
    extend_watch_state,
    morphology_breadth,
)


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


def test_morphology_breadth_has_a_fixed_transparent_denominator(monkeypatch):
    calls = iter([
        {"bias": "bullish", "bars_since": 2, "exhausted": False, "pattern": "Bull Flag", "pattern_cn": "多头旗形", "confidence": 0.8},
        {"bias": "bullish", "bars_since": 3, "exhausted": False, "pattern": "Rectangle", "pattern_cn": "矩形", "confidence": 0.78},
        {"bias": "bearish", "bars_since": 80, "exhausted": False, "pattern": "Bear Flag", "pattern_cn": "空头旗形", "confidence": 0.8},
        None,
    ])
    monkeypatch.setattr("hourly_pattern_report.analyze", lambda _: next(calls))
    result = morphology_breadth(frame(), windows=(100, 120, 140, 160))
    assert result["positive"] == 2
    assert result["negative"] == 0
    assert result["neutral"] == 2
    assert result["breadth"] == 0.5
    assert result["label"] == "偏多共振"


def test_aggregate_backtests_weights_contract_results_by_trade_count():
    universe = [
        {"backtest": {"samples": 2, "horizons": {"24": {"win_rate": 0.5, "avg_return": 0.01}}}},
        {"backtest": {"samples": 3, "horizons": {"24": {"win_rate": 2 / 3, "avg_return": -0.002}}}},
        {"backtest": {"samples": 0, "horizons": {}}},
    ]
    result = aggregate_backtests(universe)
    assert result["samples"] == 5
    assert result["horizons"]["24"]["wins"] == 3
    assert result["horizons"]["24"]["win_rate"] == 0.6
    assert round(result["horizons"]["24"]["avg_return"], 4) == 0.0028


def test_extended_watch_is_visible_but_never_trade_eligible():
    result = extend_watch_state(
        {"trade_state": "stale", "bars_since": 76, "decision_eligible": True}
    )
    assert result["trade_state"] == "aging"
    assert result["freshness_band"] == "extended_watch"
    assert result["decision_eligible"] is False


def test_technical_snapshot_uses_futures_price_and_open_interest_context():
    result = technical_snapshot(frame())
    assert result["trends"]["hourly"] == "bullish"
    assert result["rsi14"] > 50
    assert result["macd_state"] == "bullish"
    assert result["participation"] == "long_build"
    assert result["support20"] < result["resistance20"]


def test_evidence_framework_requires_two_confirmation_categories():
    row = {
        "pattern": "Bull Flag",
        "bias": "bullish",
        "trade_state": "setup",
        "reward_risk": 1.8,
        "volume_confirmed": True,
        "oi_confirmed": False,
        "technical": {
            "trends": {"hourly": "bullish", "four_hour": "bullish", "daily": "bearish"},
            "rsi14": 58,
            "macd_state": "bullish",
        },
        "morphology": {"breadth": 0.0},
        "backtest": {"samples": 3, "horizons": {}},
    }
    result = apply_evidence_framework(row)
    assert result["trend_votes"] == 2
    assert result["confluence_count"] == 2
    assert result["research_eligible"] is True
    assert result["decision_eligible"] is False


def test_portfolio_backtest_is_a_separate_promotion_gate():
    rows = [{"research_eligible": True}, {"research_eligible": False}]
    blocked = {"horizons": {"24": {
        "samples": 20, "win_rate": 0.45, "avg_return": 0.01,
    }}}
    assert apply_portfolio_gate(rows, blocked) is False
    assert rows[0]["decision_eligible"] is False

    passed = {"horizons": {"24": {
        "samples": 20, "win_rate": 0.55, "avg_return": 0.01,
    }}}
    assert apply_portfolio_gate(rows, passed) is True
    assert rows[0]["decision_eligible"] is True
    assert rows[1]["decision_eligible"] is False
