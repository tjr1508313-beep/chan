import screening.ui as ui


def test_caution_badge_md_maps_and_joins():
    md = ui._caution_badge_md("투자경고,단기과열")
    assert ":orange[투경]" in md
    assert ":orange[과열]" in md


def test_caution_badge_md_empty_returns_blank():
    assert ui._caution_badge_md(None) == ""
    assert ui._caution_badge_md("") == ""
    assert ui._caution_badge_md(float("nan")) == ""


def test_caution_badge_md_unknown_label_passthrough():
    assert ":orange[기타]" in ui._caution_badge_md("기타")
