"""Reference-line anchors from exactly the candles displayed in a stock chart."""

import numpy as np
import pandas as pd


def chart_reference_anchors(candles: pd.DataFrame) -> dict:
    """Return logical-index/price pairs; ties use the earliest candle."""
    if len(candles) < 2:
        return {}
    values = candles[["Open", "High", "Low", "Close"]].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        return {}
    high = np.maximum.reduce(values, axis=1)
    low = np.minimum.reduce(values, axis=1)
    hi, lo = int(high.argmax()), int(low.argmin())
    return {
        "openClose": [[0, float(values[0, 0])], [len(values) - 1, float(values[-1, 3])]],
        "lowHigh": [[lo, float(low[lo])], [hi, float(high[hi])]],
    }
