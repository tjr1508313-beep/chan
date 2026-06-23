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
