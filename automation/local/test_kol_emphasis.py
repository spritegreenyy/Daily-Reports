from kol_emphasis import emphasize_opinion, strip_numeric_emphasis


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
