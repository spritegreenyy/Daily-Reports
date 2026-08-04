import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "automation" / "local"))
sys.path.insert(0, str(ROOT / "kol_digest" / "scripts"))

from kol_ranking import build_rankings


def _row(handle, board, text, *, tier=2, engagement=100, important=True, tags=None):
    return {
        "h": handle,
        "b": board,
        "x_zh": text,
        "x_en": text,
        "tier": tier,
        "eng": engagement,
        "important": important,
        "tags": tags or ["viewpoint"],
        "t": "2026-08-04T01:00:00+00:00",
        "u": f"https://example.com/{handle}",
    }


def test_rankings_score_market_views_above_off_topic_engagement():
    rows = [
        _row("offtopic", "macro", "The longest eclipse will wake the mummy next year.", engagement=5000),
        _row("macropro", "macro", "Inflation is falling, so I expect the Fed to cut rates and Treasury yields to decline.", tier=1, engagement=500),
    ]
    result = build_rankings(rows, "2026-08-04T03:00:00+00:00")
    assert result["top_views"][0]["handle"] == "macropro"
    assert "offtopic" not in {item["handle"] for item in result["top_views"]}


def test_rankings_diversify_handles_and_boards():
    rows = []
    for index in range(4):
        rows.append(_row(f"macro{index}", "macro", f"Inflation risk {index} means rates may rise and bonds may sell off.", tier=1, engagement=1000-index))
    rows.extend([
        _row("oil", "commodities", "Oil supply is tightening while demand rises, so crude has upside risk.", tier=1, engagement=700),
        _row("ai", "ai_semis", "AI inference demand is rising and GPU supply remains tight, supporting semiconductor capex.", tier=1, engagement=600),
        _row("geo", "geopolitics", "Iran conflict escalation raises sanctions and oil supply disruption risk.", tier=1, engagement=500),
    ])
    result = build_rankings(rows, "2026-08-04T03:00:00+00:00")
    assert len(result["top_views"]) == 5
    assert sum(item["board"] == "macro" for item in result["top_views"]) <= 2
    assert len({item["handle"] for item in result["top_views"]}) == 5


def test_kol_score_rewards_consistent_quality():
    rows = [
        _row("steady", "macro", "Fed inflation risk implies rates stay high and bond yields rise.", tier=1, engagement=300),
        _row("steady", "commodities", "Oil supply remains tight, so crude prices have upside risk.", tier=1, engagement=250),
        _row("oneoff", "macro", "Inflation risk implies rates stay high.", tier=1, engagement=300),
    ]
    result = build_rankings(rows, "2026-08-04T03:00:00+00:00")
    scores = {item["handle"]: item["score"] for item in result["top_kols"]}
    assert scores["steady"] > scores["oneoff"]
