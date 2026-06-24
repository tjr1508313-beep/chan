import math
from screening.betting import compute_bet_rows


def _kr(ticker, name, price, atr9):
    return {"ticker": ticker, "name": name, "spec_code": "kr", "price": price, "atr9": atr9}


def test_kr_single_pick_three_way_split():
    picks = [_kr("000001", "A", 45000.0, 1800.0)]
    out = compute_bet_rows(
        picks, portfolio_won=15_000_000, risk_pct=1.0,
        stop_n_mult=2.0, split_count=3, fx_rate=1380.0,
    )
    assert out["total_risk"] == 150_000
    assert out["per_risk"] == 50_000          # 150,000 / 3
    row = out["rows"][0]
    assert row["per_share_risk"] == 3600.0    # 1800 * 2
    assert row["stop_price"] == 41_400.0      # 45000 - 3600
    assert row["shares"] == 13                # floor(50000 / 3600)
    assert row["invest_native"] == 585_000.0  # 13 * 45000
    assert out["total_invest_won"] == 585_000
    assert out["cash_left_won"] == 14_415_000
    assert abs(out["asset_pct"] - 585_000 / 15_000_000) < 1e-9


def test_split_count_changes_shares():
    picks = [_kr("000001", "A", 45000.0, 1800.0)]
    out2 = compute_bet_rows(picks, portfolio_won=15_000_000, risk_pct=1.0,
                            stop_n_mult=2.0, split_count=2, fx_rate=1380.0)
    assert out2["per_risk"] == 75_000
    assert out2["rows"][0]["shares"] == 20    # floor(75000 / 3600)


def test_zero_portfolio_yields_no_shares():
    picks = [_kr("000001", "A", 45000.0, 1800.0)]
    out = compute_bet_rows(picks, portfolio_won=0, risk_pct=1.0,
                           stop_n_mult=2.0, split_count=3, fx_rate=1380.0)
    assert out["total_risk"] == 0
    assert out["rows"][0]["shares"] == 0
    assert out["total_invest_won"] == 0


def test_zero_atr_yields_no_stop_no_shares():
    picks = [_kr("000001", "A", 45000.0, 0.0)]
    out = compute_bet_rows(picks, portfolio_won=15_000_000, risk_pct=1.0,
                           stop_n_mult=2.0, split_count=3, fx_rate=1380.0)
    assert out["rows"][0]["stop_price"] is None
    assert out["rows"][0]["shares"] == 0


def test_us_pick_converts_to_won_for_totals():
    picks = [{"ticker": "AAA", "name": "A", "spec_code": "us", "price": 100.0, "atr9": 2.0}]
    out = compute_bet_rows(picks, portfolio_won=15_000_000, risk_pct=1.0,
                           stop_n_mult=2.0, split_count=3, fx_rate=1380.0)
    row = out["rows"][0]
    assert row["currency"] == "USD"
    assert row["per_share_risk"] == 4.0                  # 2 * 2 (USD)
    assert row["per_share_risk_won"] == 4.0 * 1380.0     # 5520
    assert row["shares"] == math.floor(50_000 / 5520.0)  # 9
    assert row["stop_price"] == 96.0                     # 100 - 4
    assert row["invest_native"] == row["shares"] * 100.0
    assert row["invest_won"] == row["shares"] * 100.0 * 1380.0
