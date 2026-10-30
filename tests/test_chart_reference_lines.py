import pandas as pd

from screening.chart_geometry import chart_reference_anchors


def test_reference_anchors_use_displayed_endpoints_and_extreme_dates():
    df = pd.DataFrame({"Open": [10, 12, 11], "High": [13, 18, 14],
                       "Low": [8, 9, 6], "Close": [12, 11, 13]})
    assert chart_reference_anchors(df) == {
        "openClose": [[0, 10.0], [2, 13.0]],
        "lowHigh": [[2, 6.0], [1, 18.0]],
    }


def test_invalid_or_single_candle_has_no_reference_lines():
    df = pd.DataFrame({"Open": [10, 12], "High": [13, float("inf")],
                       "Low": [8, 9], "Close": [12, 11]})
    assert chart_reference_anchors(df) == {}
    assert chart_reference_anchors(df.iloc[:1]) == {}


def test_extreme_ties_use_first_candle_and_match_candle_correction():
    df = pd.DataFrame({"Open": [20, 10], "High": [13, 20],
                       "Low": [8, 8], "Close": [12, 11]})
    assert chart_reference_anchors(df)["lowHigh"] == [[0, 8.0], [0, 20.0]]
