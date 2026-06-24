"""베팅 포지션 사이징 순수 계산 (UI/Streamlit 비의존, 테스트 대상)."""

from __future__ import annotations

import math


def compute_bet_rows(
    picks,
    *,
    portfolio_won: float,
    risk_pct: float,
    stop_n_mult: float,
    split_count: int,
    fx_rate: float,
) -> dict:
    portfolio_won = float(portfolio_won or 0)
    total_risk = int(portfolio_won * float(risk_pct or 0) / 100)
    split = max(int(split_count or 1), 1)
    per_risk = total_risk // split

    rows = []
    total_invest_won = 0.0
    total_risk_used_won = 0.0
    for p in picks or []:
        is_us = str(p.get("spec_code")) == "us"
        price = float(p.get("price") or 0)
        atr9 = float(p.get("atr9") or 0)
        n = float(stop_n_mult or 0)
        per_share_risk = atr9 * n
        per_share_risk_won = per_share_risk * (float(fx_rate) if is_us else 1.0)
        stop_price = (price - per_share_risk) if atr9 > 0 else None
        if per_share_risk_won > 0 and per_risk > 0:
            shares = math.floor(per_risk / per_share_risk_won)
        else:
            shares = 0
        invest_native = shares * price
        invest_won = invest_native * (float(fx_rate) if is_us else 1.0)
        risk_won = shares * per_share_risk_won
        total_invest_won += invest_won
        total_risk_used_won += risk_won
        rows.append({
            "ticker": p.get("ticker"),
            "name": p.get("name"),
            "spec_code": p.get("spec_code"),
            "price": price,
            "atr9": atr9,
            "currency": "USD" if is_us else "KRW",
            "stop_price": stop_price,
            "per_share_risk": per_share_risk,
            "per_share_risk_won": per_share_risk_won,
            "shares": int(shares),
            "invest_native": invest_native,
            "invest_won": invest_won,
            "risk_won": risk_won,
        })

    asset_pct = (total_invest_won / portfolio_won) if portfolio_won > 0 else 0.0
    return {
        "total_risk": total_risk,
        "per_risk": per_risk,
        "rows": rows,
        "total_invest_won": int(round(total_invest_won)),
        "total_risk_used_won": int(round(total_risk_used_won)),
        "asset_pct": asset_pct,
        "cash_left_won": int(round(portfolio_won - total_invest_won)),
    }
