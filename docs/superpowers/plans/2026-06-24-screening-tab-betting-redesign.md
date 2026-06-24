# 스크리닝 탭/ㄴ자 베팅 재설계 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 미국/한국 스크리닝을 탭으로 분리하고, 좌측 사이드바를 없애며, 베팅 사이즈 계산기를 'ㄴ'자(차트 우측 설정 + 전체 폭 종목 밴드)로 같은 화면에 배치한다.

**Architecture:** `render_screening_page()` 단일 진입점은 유지하되, 내부를 `scr_active_tab` 기반 뷰 라우터로 바꿔 활성 시장만 `_render_market_tab(spec)`로 렌더한다. 베팅 계산은 순수 함수 `screening/betting.py:compute_bet_rows`로 분리해 단위 테스트하고, UI(`_render_betting_panel`)는 그 결과만 그린다.

**Tech Stack:** Python 3.13, Streamlit 1.58, pandas, pytest. 기존 `screening/` 패키지 패턴 준수.

## Global Constraints

- session_state 키는 모두 `scr_`(미국 `scr_`, 한국 `scr_kr_`) 접두사. 신규: `scr_active_tab`(기본 "kr"), `scr_bet_split`(기본 3). picks 저장소는 기존 `scr_basket` 재사용(`spec_code`로 탭별 필터).
- `st.set_page_config()`는 `screening.py`의 `main()` 안에서만 호출.
- CSS 주입은 `screening/theme.py`의 `apply_theme()` 경유.
- `@st.cache_data` 함수는 `us_`/`screen_` 접두사. (베팅 순수 함수는 캐시 아님 → 접두사 불필요.)
- requirements는 `>=` 최소 버전.
- 색상: 수익 빨강 `#ff4b4b`(COLOR_PROFIT), 손실 파랑 `#1a9cff`(COLOR_LOSS). 라이트 테마.
- 배포: `main` push 시 Streamlit Cloud 자동 재배포 → 본 작업은 `feat/screening-tab-betting-redesign` 브랜치에서만, 푸시는 사용자 승인 후. `.bak`/`_apply/`/`screening_cache.db*` 커밋 금지.
- 분할 수 범위 1~5, 시장별 picks 최대 5.

---

## File Structure

- Create: `screening/betting.py` — 순수 베팅 포지션 계산(`compute_bet_rows`). UI 무관.
- Create: `tests/test_betting.py` — `compute_bet_rows` 단위 테스트.
- Modify: `screening/ui.py` — 탭 라우터, `_render_market_tab`, `_render_betting_panel`, `_render_filter_controls`/`_build_filter_config`, ＋담기, 사이드바 제거.
- Modify: `screening/theme.py` — 탭/밴드/베팅 CSS.
- Modify: `screening.py` — `initial_sidebar_state="collapsed"`.

---

## Task 1: 완료된 데이터-로직 변경 베이스라인 커밋

이미 구현·테스트된 변경(섹터 필터 3,000억·100억, `exclude_caution`, 초기 UI 다듬기)을 브랜치에 베이스라인으로 커밋해 작업 트리를 정리한다. 신규 코드 없음.

**Files:**
- Modify(이미 변경됨): `screening/sector.py`, `screening/core.py`, `screening/ui.py`, `screening/theme.py`, `CLAUDE.md`, `tests/test_core_risk.py`

- [ ] **Step 1: 전체 테스트 통과 확인**

Run: `py -m pytest -q`
Expected: PASS (59+ passed)

- [ ] **Step 2: 데이터-로직 + 초기 UI 변경만 스테이징**

```bash
git add screening/sector.py screening/core.py screening/ui.py screening/theme.py CLAUDE.md tests/test_core_risk.py
```
(주의: 작업 트리의 기존 미관련 변경 — `cache.py`, `scripts/refresh_cache.py`, `tests/test_sector_snapshot.py`, `tests/test_ui_sector_panel.py`, `.claude/` 등 — 은 스테이징하지 말 것. `git status`로 확인.)

- [ ] **Step 3: 커밋**

```bash
git commit -m "섹터 왜곡 컷(시총 3000억·거래대금 100억·exclude_caution) + 상단 UI 정리

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 베팅 포지션 계산 순수 함수 (`screening/betting.py`)

**Files:**
- Create: `screening/betting.py`
- Test: `tests/test_betting.py`

**Interfaces:**
- Consumes: 없음(순수 함수).
- Produces: `compute_bet_rows(picks, *, portfolio_won, risk_pct, stop_n_mult, split_count, fx_rate) -> dict`
  - `picks`: list of `{"ticker": str, "name": str, "spec_code": "kr"|"us", "price": float, "atr9": float}`
  - 반환 dict 키: `total_risk`(int, 원), `per_risk`(int, 원=total_risk//split_count), `rows`(list), `total_invest_won`(int), `total_risk_used_won`(int), `asset_pct`(float, 0~1), `cash_left_won`(int)
  - `rows[i]` 키: `ticker, name, spec_code, price, atr9, currency("KRW"|"USD"), stop_price(float|None), per_share_risk(float, native), per_share_risk_won(float), shares(int), invest_native(float), invest_won(float), risk_won(float)`
  - 규칙: `per_share_risk = atr9*stop_n_mult`(native). US는 `per_share_risk_won = per_share_risk*fx_rate`, KR은 동일. `shares = floor(per_risk / per_share_risk_won)` (per_share_risk_won>0, per_risk>0 일 때, 아니면 0). `stop_price = price - per_share_risk` (atr9>0 일 때, 아니면 None). `invest_native = shares*price`, `invest_won = invest_native*(fx_rate if us else 1)`, `risk_won = shares*per_share_risk_won`. 합계는 won 기준.

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/test_betting.py`:
```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `py -m pytest tests/test_betting.py -q`
Expected: FAIL (ModuleNotFoundError: screening.betting)

- [ ] **Step 3: 최소 구현 작성**

Create `screening/betting.py`:
```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `py -m pytest tests/test_betting.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add screening/betting.py tests/test_betting.py
git commit -m "베팅 포지션 사이징 순수 계산 모듈 추가(compute_bet_rows)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: 탭 라우터 + 사이드바 접기

`render_screening_page()`를 활성 시장만 렌더하는 탭 라우터로 바꾼다. 이 태스크에서는 기존 `_render_screening_section`을 그대로 활성 탭에만 호출(레이아웃 전면 개편은 Task 4).

**Files:**
- Modify: `screening.py` (`main()`의 `set_page_config`)
- Modify: `screening/ui.py` (`render_screening_page`, 신규 `_render_tab_bar`)

**Interfaces:**
- Consumes: 기존 `_render_sidebar`, `_render_market_card`, `_render_market_index_chart`, `_render_screening_section`, `_get_inline_settings`, `_US_SPEC`, `_KR_SPEC`.
- Produces: `st.session_state["scr_active_tab"]` ∈ {"kr","us"}.

- [ ] **Step 1: set_page_config에 사이드바 접기 추가**

`screening.py`의 `main()` 내 `st.set_page_config(...)` 호출에 `initial_sidebar_state="collapsed"` 인자를 추가한다. (기존 인자 유지. 호출이 없으면 `layout="wide"`와 함께 추가.)

- [ ] **Step 2: 탭 바 + 라우터로 `render_screening_page` 교체**

`screening/ui.py:2615` `render_screening_page` 본문을 아래로 교체. 사이드바의 베팅/시장 설정 호출은 제거하고, 활성 탭 1개만 렌더:
```python
def render_screening_page() -> None:
    _load_prefs()
    st.session_state.setdefault("scr_active_tab", "kr")

    active = _render_tab_bar()
    spec = _KR_SPEC if active == "kr" else _US_SPEC

    filter_config = _render_sidebar(spec)  # 임시: Task 5에서 본문 컨트롤로 이전
    index_code, rs_period, top_n = _get_inline_settings(spec)
    settings = (index_code, rs_period, top_n, filter_config)

    _render_market_card(spec, settings)
    _render_market_index_chart(spec, settings[0])
    _render_screening_section(spec, settings)


def _render_tab_bar() -> str:
    tabs = [("kr", "한국주식"), ("us", "미국주식")]
    cols = st.columns(len(tabs) + 4)
    for i, (code, label) in enumerate(tabs):
        with cols[i]:
            is_on = st.session_state.get("scr_active_tab") == code
            if st.button(
                label, key=f"scr_tab_btn_{code}",
                type="primary" if is_on else "secondary",
                use_container_width=True,
            ):
                st.session_state["scr_active_tab"] = code
                st.rerun()
    return st.session_state.get("scr_active_tab", "kr")
```
(주의: `_render_sidebar`는 내부에서 `with st.sidebar:`로 그리므로, 접힌 사이드바에 잠시 남는다 — Task 5에서 본문 이전 후 제거. 이 태스크의 목표는 "활성 탭만 렌더 + 탭 전환 동작".)

- [ ] **Step 3: 임포트/스모크 확인**

Run: `py -c "import ast; ast.parse(open('screening/ui.py',encoding='utf-8').read()); ast.parse(open('screening.py',encoding='utf-8').read()); print('AST OK')"`
Then: `py -c "import screening.ui, screening; print('IMPORT OK')"`
Expected: `AST OK` / `IMPORT OK`

- [ ] **Step 4: 회귀 테스트**

Run: `py -m pytest -q`
Expected: PASS (기존 + betting 테스트)

- [ ] **Step 5: 수동 확인 + 커밋**

수동: `py -m streamlit run screening.py` → 상단 [한국주식][미국주식] 버튼으로 전환되고, 기본 한국주식이 뜨며, 미국 클릭 시 미국만 렌더되는지 확인(시각 검증은 사용자).
```bash
git add screening/ui.py screening.py
git commit -m "탭 라우터로 전환(활성 시장만 렌더) + 사이드바 접기

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: ㄴ자 레이아웃 + 베팅 패널 (`_render_market_tab`, `_render_betting_panel`)

활성 탭 본문을 ㄴ자 레이아웃으로 재구성하고 베팅 패널을 붙인다.

**Files:**
- Modify: `screening/ui.py` (신규 `_render_market_tab`, `_render_betting_panel`; `render_screening_page`에서 호출)

**Interfaces:**
- Consumes: `compute_bet_rows`(Task 2), 기존 `_render_market_card`/`_render_market_index_chart`/`_render_screening_section`, 베팅 prefs(`scr_portfolio_value`/`scr_risk_pct`/`scr_stop_n_mult`/`scr_fx_rate`), `_ensure_basket`/`_basket_remove`/`_BASKET_KEY`, `_save_prefs`.
- Produces: `_render_market_tab(spec, settings)`; `st.session_state["scr_bet_split"]`(int).

- [ ] **Step 1: `render_screening_page`가 `_render_market_tab` 호출하도록 변경**

Task 3의 본문 마지막 3줄(`_render_market_card`/`_render_market_index_chart`/`_render_screening_section`)을 `_render_market_tab(spec, settings)` 한 줄로 교체.

- [ ] **Step 2: `_render_market_tab` 구현**

```python
def _render_market_tab(spec: dict, settings: tuple) -> None:
    top_l, top_r = st.columns([1.5, 1], gap="medium")
    with top_l:
        _render_market_card(spec, settings)
        _render_market_index_chart(spec, settings[0])
    with top_r:
        _render_betting_panel(spec, position="settings")
    _render_betting_panel(spec, position="band")   # 전체 폭 밴드
    _render_screening_section(spec, settings)        # 컨트롤+섹터/종목(전체 폭)
```

- [ ] **Step 3: `_render_betting_panel` 구현 (settings + band)**

`spec_code = spec["code"]` 의 picks만 필터링. 자산/리스크/손절/분할 입력은 `position=="settings"`에서, 밴드+합계는 `position=="band"`에서 렌더. 계산은 `compute_bet_rows`:
```python
def _render_betting_panel(spec: dict, *, position: str) -> None:
    spec_code = spec["code"]
    basket = [b for b in _ensure_basket() if b.get("spec_code") == spec_code]
    portfolio_won = int(st.session_state.get("scr_portfolio_value", 0)) * 10_000
    result = compute_bet_rows(
        basket,
        portfolio_won=portfolio_won,
        risk_pct=float(st.session_state.get("scr_risk_pct", 1.0)),
        stop_n_mult=float(st.session_state.get("scr_stop_n_mult", 2.0)),
        split_count=int(st.session_state.get("scr_bet_split", 3)),
        fx_rate=float(st.session_state.get("scr_fx_rate", 1380.0)),
    )

    if position == "settings":
        st.markdown("##### 베팅 설정")
        c = st.columns(2)
        with c[0]:
            st.number_input("자산(만원)", min_value=0, step=1, format="%d",
                            key="scr_portfolio_value", on_change=_save_prefs)
            st.number_input("손절 N배", min_value=0.5, max_value=5.0, step=0.5,
                            format="%.1f", key="scr_stop_n_mult", on_change=_save_prefs)
        with c[1]:
            st.number_input("리스크 %", min_value=0.1, max_value=10.0, step=0.1,
                            format="%.1f", key="scr_risk_pct", on_change=_save_prefs)
            st.number_input("분할 수", min_value=1, max_value=5, step=1, format="%d",
                            key="scr_bet_split",
                            value=int(st.session_state.get("scr_bet_split", 3)))
        st.caption(f"총 리스크 예산 ₩{result['total_risk']:,} · 종목당 ₩{result['per_risk']:,}")
        return

    # position == "band"
    st.markdown("##### 베팅 종목")
    if not basket:
        st.caption("아래 종목 리스트의 ‘＋담기’로 추가하세요. (최대 5)")
        return
    cols = st.columns(min(len(result["rows"]), 5) + 1)
    to_remove = []
    for i, row in enumerate(result["rows"][:5]):
        with cols[i]:
            cur = "₩" if row["currency"] == "KRW" else "$"
            dec = 0 if row["currency"] == "KRW" else 2
            stop_txt = f"{cur}{row['stop_price']:,.{dec}f}" if row["stop_price"] is not None else "—"
            sh = row["shares"]
            inv = f"{cur}{row['invest_native']:,.{dec}f}" if sh else "—"
            st.markdown(
                f"**{row['name']}**  {cur}{row['price']:,.{dec}f}<br>"
                f"<span style='color:{COLOR_MUTED};font-size:0.78rem'>"
                f"손절 {stop_txt} · 주당 {cur}{row['per_share_risk']:,.{dec}f}</span><br>"
                f"<span style='color:{COLOR_PROFIT};font-weight:600'>{sh:,}주 · {inv}</span>",
                unsafe_allow_html=True,
            )
            if st.button("×", key=f"scr_bet_rm_{spec_code}_{row['ticker']}"):
                to_remove.append(row["ticker"])
    with cols[min(len(result["rows"]), 5)]:
        st.markdown(
            f"**합계**<br><span style='font-size:0.8rem'>"
            f"투자 ₩{result['total_invest_won']:,}<br>"
            f"리스크 ₩{result['total_risk_used_won']:,}<br>"
            f"자산대비 {result['asset_pct']*100:.1f}%<br>"
            f"잔여 ₩{result['cash_left_won']:,}</span>",
            unsafe_allow_html=True,
        )
    for t in to_remove:
        _basket_remove(t)
    if to_remove:
        st.rerun()
```
(주의: `scr_bet_split`에 `value=`와 `key=` 동시 지정은 최초 1회만 유효 — 이미 session_state에 있으면 Streamlit이 경고하지 않도록 `st.session_state.setdefault("scr_bet_split", 3)`를 `render_screening_page` 초기에 두고 `value=` 제거. 구현 시 setdefault 방식 사용.)

- [ ] **Step 4: 임포트/스모크 + 회귀**

Run: `py -c "import screening.ui; print('IMPORT OK')"` then `py -m pytest -q`
Expected: `IMPORT OK` / PASS

- [ ] **Step 5: 수동 확인 + 커밋**

수동: 앱 실행 → 차트 우측 베팅 설정, 그 아래 밴드(담은 종목 없으면 안내), 분할 수 변경 시 갱신 확인.
```bash
git add screening/ui.py
git commit -m "ㄴ자 레이아웃 + 베팅 패널(설정/밴드/합계) 추가

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 컨트롤·필터 본문 이전 + 사이드바 제거 + ＋담기

사이드바 위젯(데이터 새로고침·필터·즐겨찾기·지수 상태)을 본문 컨트롤 줄로 옮기고, 종목 리스트에 ＋담기 버튼을 추가한다. 종목 상세는 정보+차트만(베팅 숫자 없음) 유지.

**Files:**
- Modify: `screening/ui.py` (`_render_sidebar` 분리, `_render_filter_controls`/`_build_filter_config` 신설, `_render_screening_section`/종목 행에 ＋담기, `render_screening_page`에서 사이드바 호출 제거)

**Interfaces:**
- Consumes: 기존 `_render_refresh_section`, `_render_index_status_badge`, `_render_fav_toggle_sidebar`, 필터 위젯들, 종목 행 렌더(`_render_ranking_table`/`_render_sector_member_rows`), 차트의 기존 "바구니에 담기" 핸들러(price+atr9 확보 로직).
- Produces: `_build_filter_config(spec) -> dict`, `_render_filter_controls(spec)`.

- [ ] **Step 1: filter_config 빌드와 위젯 렌더 분리**

`_render_sidebar`(`ui.py:702`)를 둘로 나눈다: ① `_build_filter_config(spec)` — `with st.sidebar:` 제거하고 필터 위젯을 `st.expander("필터 설정")` 안에서 렌더한 뒤 dict 반환(기존 800~804 라인 dict 그대로). ② 새로고침/지수상태/즐겨찾기는 `_render_filter_controls(spec)`에서 본문에 렌더. 두 함수 모두 `with st.sidebar:` 없이 본문 컨텍스트에서 호출.

- [ ] **Step 2: `_render_screening_section` 상단에 컨트롤 줄 배치**

`_render_screening_section`(`ui.py:2099`) 시작부에서 한 줄 컨트롤을 렌더: `st.columns`로 [지수/기간/표시(기존 `_render_rs_header` 컨트롤)] + [필터 expander] + [새로고침]. 기존 `_render_rs_header` 호출은 컨트롤만 남도록 정리(제목/기간정보는 이미 제거됨).

- [ ] **Step 3: 종목 행에 ＋담기 추가**

종목 리스트(전체 RS 표 `_render_ranking_table`, 섹터 멤버 `_render_sector_member_rows`)의 각 행에 ＋담기 버튼을 추가한다. 클릭 시 해당 종목의 price+atr9를 확보(기존 차트용 "바구니에 담기"가 쓰는 동일 로직/헬퍼 재사용)해 `scr_basket`에 `{ticker, name, spec_code, price, atr9}`로 추가(중복·최대 5 가드). 기존 차트의 "바구니에 담기" 버튼은 유지하거나 ＋담기로 일원화(구현 시 단순화 우선 — 행 버튼으로 일원화 권장).

- [ ] **Step 4: 사이드바 호출 제거**

`render_screening_page`에서 `_render_sidebar(spec)` 호출을 `_build_filter_config(spec)`로 교체하고, 베팅/시장 사이드바 렌더 호출은 모두 제거. `_render_betting_calculator_and_basket_sidebar`는 더 이상 사용 안 함(데드코드 — 제거).

- [ ] **Step 5: 임포트/스모크 + 회귀**

Run: `py -c "import screening.ui; print('IMPORT OK')"` then `py -m pytest -q`
Expected: `IMPORT OK` / PASS (UI 패널 테스트가 사이드바 함수에 의존하면 해당 테스트도 함께 업데이트)

- [ ] **Step 6: 수동 확인 + 커밋**

수동: 사이드바 비어 접힘, 본문에서 새로고침/필터 동작, 종목 ＋담기 → 밴드 반영, 종목 클릭 시 차트는 정보만.
```bash
git add screening/ui.py tests/
git commit -m "사이드바 제거·컨트롤 본문 이전 + 종목 ＋담기 → 베팅 밴드

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: 테마 CSS 마감 + 전체 검증

**Files:**
- Modify: `screening/theme.py`

- [ ] **Step 1: 탭/밴드/베팅 CSS 추가**

`theme.py`의 `_CSS`(또는 신규 블록)에 탭 버튼 강조(active=빨강 테두리), 베팅 밴드 칸 카드(0.5px 보더, radius), 합계 칸 강조 스타일을 추가하고 `apply_theme()`에서 주입되는지 확인. 라이트 테마 색만 사용.

- [ ] **Step 2: 전체 테스트**

Run: `py -m pytest -q`
Expected: PASS (전체)

- [ ] **Step 3: 임포트 스모크**

Run: `py -c "import screening.ui, screening.theme, screening.betting, screening; print('OK')"`
Expected: `OK`

- [ ] **Step 4: 수동 검증 체크리스트(사용자)**

- 기본 한국주식 탭, 상단 [한국][미국] 전환.
- 차트 우측 베팅 설정 + 전체 폭 밴드, 분할 수 1~5 변경 시 수량/투자금/합계 즉시 갱신.
- 종목 ＋담기 → 밴드 칸 추가(최대 5), × 제거.
- 미국 탭 동일 동작, $ 표기·환율 환산.
- 사이드바 비어 접힘, 상단 여백 정상.

- [ ] **Step 5: 커밋**

```bash
git add screening/theme.py
git commit -m "탭/베팅 밴드 테마 CSS 마감

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review 결과

- **Spec 커버리지**: 탭 라우터(Task3)·ㄴ자 레이아웃/베팅 패널(Task4)·분할 수 계산(Task2)·사이드바 제거·컨트롤 이전·＋담기(Task5)·CSS(Task6)·기존 데이터변경 베이스라인(Task1) — spec 4.1~4.6 및 6·7 항목 모두 태스크 매핑됨.
- **플레이스홀더**: 없음(코드 스텝은 실제 코드 포함). UI 일부는 기존 함수 재사용 지시 — 구현 시 해당 함수 시그니처 확인 필요.
- **타입 일관성**: `compute_bet_rows` 반환 키를 Task4 UI가 동일 명칭으로 소비(`total_risk`/`per_risk`/`rows`/`stop_price`/`per_share_risk`/`shares`/`invest_native`/`total_invest_won`/`total_risk_used_won`/`asset_pct`/`cash_left_won`).
- **주의(구현자 확인 필요)**: 차트의 기존 "바구니에 담기"가 price+atr9를 만드는 정확한 코드 경로(Task5 Step3)와, 사이드바 함수에 의존하는 테스트(`tests/test_ui_sector_panel.py` 등) 존재 여부 — 구현 시 grep으로 확인 후 반영.
