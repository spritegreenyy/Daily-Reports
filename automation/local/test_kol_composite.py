from kol_composite import build_composite_history, run_price_backtests


def asset(score=None, samples=0, confidence=0, mentions=0, bullish=0, bearish=0):
    return {
        "score": score,
        "signal_tweets": samples,
        "confidence": confidence,
        "mentions": mentions,
        "bullish": bullish,
        "bearish": bearish,
    }


def row(date, energy=None, metals=None, grains=None, softs=None):
    return {
        "date": date,
        "assets": {
            "energy": energy or asset(),
            "metals": metals or asset(),
            "grains": grains or asset(),
            "softs": softs or asset(),
        },
    }


def test_composite_contributions_sum_to_score_and_keep_missing_null():
    history = {"daily": [
        row("2026-01-01"),
        row(
            "2026-01-02",
            energy=asset(40, 2, 0.5, 3, 2, 0),
            metals=asset(-20, 1, 0.4, 2, 0, 1),
        ),
    ]}
    result = build_composite_history(history)["daily"]
    assert result[0]["score"] is None
    assert result[0]["coverage"] == 0
    assert result[1]["coverage"] == 50
    assert round(sum(v for v in result[1]["contributions"].values() if v is not None), 1) == result[1]["score"]


def test_disagreement_distinguishes_consensus_from_split_views():
    history = {"daily": [
        row("2026-01-01", energy=asset(30, 2, 0.5, 2, 2, 0)),
        row(
            "2026-01-02",
            energy=asset(20, 2, 0.5, 2, 1, 1),
            metals=asset(-20, 2, 0.5, 2, 1, 1),
        ),
    ]}
    result = build_composite_history(history)["daily"]
    assert result[0]["disagreement"] == 0
    assert result[1]["disagreement"] == 100


def test_price_backtest_reports_directional_return_win_rate_and_ic():
    daily = [
        {"date": "2026-01-01", "score": 30},
        {"date": "2026-01-02", "score": -40},
        {"date": "2026-01-03", "score": 20},
    ]
    prices = {"原油": {
        "2026-01-01": 100,
        "2026-01-02": 110,
        "2026-01-03": 99,
        "2026-01-04": 108,
    }}
    metrics = run_price_backtests(daily, prices, horizons=(1,))["products"]["原油"]["1"]
    assert metrics["n"] == 3
    assert metrics["win_rate"] == 100
    assert metrics["avg_directional_return"] > 8
    assert metrics["ic"] > 0
