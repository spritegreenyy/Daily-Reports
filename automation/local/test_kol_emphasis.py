from kol_emphasis import compact_core_points, emphasize_opinion, strip_numeric_emphasis


def test_numbers_are_not_selected_as_emphasis():
    rendered = emphasize_opinion("美元需贬值83-90%，黄金将受益。")
    assert "83-90%" in rendered
    assert '<b class="em">83-90%</b>' not in rendered
    assert '<b class="em">黄金将受益。</b>' in rendered


def test_conclusion_is_emphasized_instead_of_key_data():
    assert emphasize_opinion("关键数据：447、14、409") == "关键数据：447、14、409"
    rendered = emphasize_opinion("钻探活动增加，预计未来几个月产量上升。")
    assert "预计未来几个月产量上升" in rendered
    assert '<b class="em">几个月</b>' not in rendered


def test_legacy_numeric_bold_is_removed_recursively():
    payload = {"points": ['黄金将<b class="em">受益</b>，上涨<b class="em">12%</b>']}
    cleaned = strip_numeric_emphasis(payload)
    assert '<b class="em">受益</b>' in cleaned["points"][0]
    assert '<b class="em">12%</b>' not in cleaned["points"][0]


def test_core_points_keep_only_view_and_conclusion():
    points = [
        "@KOL：黄金将受益。",
        "交易含义：黄金可能长期重估",
        "关键数据：1971、83、90%",
        "互动 611+ · 来自宏观经济板块",
    ]
    assert compact_core_points(points) == [
        "核心观点：@KOL：黄金将受益。",
        "交易结论：黄金可能长期重估",
    ]
    assert compact_core_points(['<b class="em">交易含义：油价承压</b>']) == [
        '交易结论：<b class="em">油价承压</b>'
    ]
