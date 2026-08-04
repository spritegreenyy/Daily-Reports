import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "kol_digest" / "scripts"))

from kol_anomalies import detect_anomalies


def _view(handle, board, *, direction=1, score=75, influence=85, tags=None):
    return {
        "handle": handle,
        "board": board,
        "direction": direction,
        "score": score,
        "influence_score": influence,
        "breakdown": {"stance": 15},
        "tags": tags or ["viewpoint"],
        "text_zh": f"{handle} 的明确观点",
        "text_en": f"Explicit view from {handle}",
        "url": f"https://example.com/{handle}",
    }


def test_detects_follower_spike_and_extreme_stance():
    snapshot = {
        "growth_leaders": [{"handle": "fast", "followers_count": 100_000, "delta_1d": 2_500, "growth_1d_pct": 2.5}],
    }
    result = detect_anomalies([_view("macro", "macro", tags=["contrarian_signal"])], snapshot, {})
    types = {item["type"] for item in result["alerts"]}
    assert "follower_spike" in types
    assert "extreme_stance" in types
    assert result["status"] == "active"


def test_detects_directional_crowding():
    views = [_view(f"oil{i}", "commodities", direction=1, influence=40) for i in range(5)]
    result = detect_anomalies(views, {}, {})
    crowding = [item for item in result["alerts"] if item["type"] == "consensus_crowding"]
    assert crowding
    assert "100%" in crowding[0]["summary_zh"]


def test_detects_attention_surge_against_history():
    views = [_view(f"ai{i}", "ai_semis", direction=0, influence=40) for i in range(8)]
    views += [_view("macro", "macro", direction=0, influence=40)]
    baseline = {"boards": {"ai_semis": {"mean": 0.20, "std": 0.05, "samples": 20}}}
    result = detect_anomalies(views, {}, baseline)
    assert any(item["type"] == "attention_surge" for item in result["alerts"])


def test_no_alert_when_thresholds_not_met():
    views = [_view("quiet", "macro", direction=0, score=50, influence=20, tags=["viewpoint"])]
    result = detect_anomalies(views, {}, {})
    assert result["status"] == "normal"
    assert result["alerts"] == []
