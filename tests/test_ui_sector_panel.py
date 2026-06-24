import pandas as pd

import screening.ui as ui


def test_format_sector_summary_displays_leading_sector():
    summary = pd.DataFrame(
        [
            {
                "rank": 1,
                "sector": "반도체",
                "sector_score": 0.1234,
                "positive_ratio": 0.5,
                "stock_count": 2,
                "top_ticker": "000660",
                "top_name": "SK하이닉스",
                "top_rs_weighted": 1.234,
            }
        ]
    )

    result = ui._format_sector_summary(summary)

    assert result.to_dict("records") == [
        {
            "순위": 1,
            "섹터": "반도체",
            "섹터점수": "+12.34%",
            "양수비율": "50.00%",
            "종목수": 2,
            "1등 종목": "000660 SK하이닉스",
            "RS가중": "1.234",
        }
    ]


def test_format_sector_members_displays_member_metrics():
    spec = {
        "ticker_col_label": "코드",
        "price_chart_fmt": lambda value: f"₩{value:,.0f}",
        "dv_label": "거래대금(억)",
        "dv_divisor": 100_000_000.0,
    }
    members = pd.DataFrame(
        [
            {
                "rank_in_sector": 1,
                "ticker": "000660",
                "name_kr": "SK하이닉스",
                "name_en": "",
                "return_n": 0.5,
                "rs": 0.33,
                "rs_weighted": 1.5,
                "last_price": 100000.0,
                "avg_traded_value_20d": 200_000_000_000.0,
            }
        ]
    )

    result = ui._format_sector_members(spec, members)

    assert result.to_dict("records") == [
        {
            "순위": 1,
            "코드": "000660",
            "종목명": "SK하이닉스",
            "수익률": "+50.00%",
            "RS": "0.3300",
            "RS가중": "1.500",
            "현재가": "₩100,000",
            "거래대금(억)": "2,000.0",
        }
    ]


def test_hex_blend_midpoint():
    assert ui._hex_blend("#000000", "#ffffff", 0.5) == "#808080"
    assert ui._hex_blend("#000000", "#ffffff", 0.0) == "#000000"
    assert ui._hex_blend("#ff0000", "#0000ff", 1.0) == "#0000ff"


def test_sector_tint_sign_and_nan():
    assert ui._sector_tint(0.18)["fg"] == "#c0392b"      # 강세 → 빨강
    assert ui._sector_tint(-0.05)["fg"] == "#1a7fd0"     # 약세 → 파랑
    assert ui._sector_tint(float("nan"))["fg"] == "#c0392b"  # NaN → 0 취급(빨강계)
    # 강도가 클수록 칩 글자색이 흰색으로 전환
    assert ui._sector_tint(0.18)["chip_fg"] == "#ffffff"
    assert ui._sector_tint(0.01)["chip_fg"] == "#c0392b"


def _sample_summary():
    return pd.DataFrame(
        [
            {"rank": 1, "sector": "반도체", "sector_score": 0.182, "positive_ratio": 0.80,
             "stock_count": 24, "avg_rs": 0.12, "top_ticker": "042700", "top_name": "한미반도체"},
            {"rank": 2, "sector": "2차전지", "sector_score": 0.124, "positive_ratio": 0.65,
             "stock_count": 31, "avg_rs": 0.06, "top_ticker": "247540", "top_name": "에코프로비엠"},
            {"rank": 3, "sector": "은행", "sector_score": -0.014, "positive_ratio": 0.40,
             "stock_count": 10, "avg_rs": -0.02, "top_ticker": "105560", "top_name": "KB금융"},
        ]
    )


def test_build_sector_metrics_counts_up_sectors_and_leader():
    html = ui._build_sector_metrics_html(_sample_summary())
    assert "2<span" in html and "/ 3</span>" in html   # 상승 섹터 2 / 3
    assert "반도체" in html and "+18.20%" in html        # 최강 섹터 = 1행


def test_build_sector_tiles_css_keys_and_selection():
    summary = _sample_summary()
    css = ui._build_sector_tiles_css(summary, "KS11", selected="2차전지")
    # 섹터 순위(rank)별 per-key 규칙
    assert ".st-key-sectile_KS11_1 button" in css
    assert ".st-key-sectile_KS11_2 button" in css
    # 선택된 섹터(2차전지, rank 2)는 2px 강조 테두리
    assert "border:2px solid" in css
    # 약세 섹터(은행)는 파랑 글자색
    assert "#1a7fd0" in css
