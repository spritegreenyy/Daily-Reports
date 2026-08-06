import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "kol_digest" / "scripts"))

from build_web import classify_tweet_board, regroup_report_sections


def test_three_commodity_families_and_nested_weather():
    assert classify_tweet_board("commodities", "Brent crude and LNG", []) == "energy"
    assert classify_tweet_board("commodities", "Gold and copper", []) == "metals"
    assert classify_tweet_board("softs", "Coffee and cocoa", []) == "agriculture"
    assert classify_tweet_board("weather", "A major heatwave", []) == "agriculture"


def test_cross_commodity_comment_is_not_forced_into_wrong_family():
    assert classify_tweet_board("commodities", "A broad commodity breakout", []) == "commodities"


def test_report_moves_weather_under_agriculture():
    report = {
        "sections": [
            ["大宗商品", [["原油", [["@oil", "", "Brent crude supply"]]], ["金属", [["@gold", "", "Gold breakout"]]]]],
            ["天气气候", [["天气气候", [["@wx", "", "Heatwave"]]]]],
        ]
    }
    result = regroup_report_sections(report, "zh")
    sections = {section[0]: section[1] for section in result["sections"]}
    assert set(sections) == {"能源", "金属", "农产品"}
    assert sections["农产品"][0][0] == "天气气候"
