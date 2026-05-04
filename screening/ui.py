"""스크리닝 앱 UI 렌더링 함수.

통합 대비 규칙:
    - 모든 session_state 키는 `scr_` 접두사 사용 (예: `scr_rs_period`)
    - `@st.cache_data` 로 감싼 함수는 `ui_` / `screen_` 접두사
    - 화면 렌더링만 담당. RS 계산/필터링은 `screening.core`,
      데이터 조회는 `screening.data` / `screening.batch` 로 위임.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from .batch import screen_refresh_index, screen_refresh_meta, screen_refresh_prices
from .batch_kr import (
    screen_refresh_index_kr,
    screen_refresh_meta_kr,
    screen_refresh_prices_kr,
)
from .cache import (
    cache_get_all_last_price_dates,
    cache_load_index,
    cache_load_prices,
)
from .core import screen_apply_filters, screen_build_screening_df, screen_rank_rs
from .data import us_get_nasdaq_tickers, us_get_sp500_tickers
from .data_kr import kr_get_kosdaq_tickers, kr_get_kospi_tickers
from .theme import (
    COLOR_BORDER,
    COLOR_CARD,
    COLOR_LOSS,
    COLOR_MUTED,
    COLOR_PROFIT,
    COLOR_TEXT,
)


# ─── 차트 색상 (나중에 theme.py 로 이관 예정) ────────────────────────────
# 한국식 색상 체계: 상승=빨강, 하락=파랑
_COLOR_UP = COLOR_PROFIT       # #ff4b4b
_COLOR_DOWN = COLOR_LOSS        # #1a9cff
_COLOR_MA = "#ff9500"           # 5일 이평선 (주황) — 라이트 배경에 대비 강화
_COLOR_ATR = "#6366f1"          # 9일 ATR (인디고)
_COLOR_ATR_FILL = "rgba(99, 102, 241, 0.15)"  # ATR 음영


# ─── session_state 키 상수 (접두사 일관성) ────────────────────────────
KEY_ASSET_CLASS = "scr_asset_class"
KEY_SELECTED_INDEX = "scr_selected_index"
KEY_RS_PERIOD = "scr_rs_period"
KEY_TOP_N = "scr_top_n"
KEY_REFRESH_LIMIT = "scr_refresh_limit"
KEY_SELECTED_TICKER = "scr_selected_ticker"
KEY_SELECTED_ROW = "scr_selected_row"  # st.dataframe selection 저장용

# 필터 설정 키
KEY_FILTER_MIN_PRICE = "scr_filter_min_price"
KEY_FILTER_MIN_DOLLAR_VOL_M = "scr_filter_min_dollar_volume_m"  # 백만$ 단위
KEY_FILTER_MAX_RANGE_PCT = "scr_filter_max_range_pct"
KEY_FILTER_EXCLUDE_CHINA = "scr_filter_exclude_china"
KEY_FILTER_EXCLUDE_RISK = "scr_filter_exclude_risk"

# 한국주식 전용 키 (미국과 분리 — 자산군 별 사이드바 독립 유지)
KEY_KR_SELECTED_INDEX = "scr_kr_selected_index"
KEY_KR_RS_PERIOD = "scr_kr_rs_period"
KEY_KR_TOP_N = "scr_kr_top_n"
KEY_KR_REFRESH_LIMIT = "scr_kr_refresh_limit"
KEY_KR_SELECTED_TICKER = "scr_kr_selected_ticker"
KEY_KR_SELECTED_ROW = "scr_kr_selected_row"
KEY_KR_FILTER_MIN_PRICE = "scr_kr_filter_min_price"
KEY_KR_FILTER_MIN_AMOUNT_E = "scr_kr_filter_min_amount_e"      # 거래대금 (억원)
KEY_KR_FILTER_MIN_MARKETCAP_E = "scr_kr_filter_min_marketcap_e"  # 시가총액 (억원)
KEY_KR_FILTER_MAX_RANGE_PCT = "scr_kr_filter_max_range_pct"
KEY_KR_FILTER_EXCLUDE_RISK = "scr_kr_filter_exclude_risk"


# ─── 데이터 획득 (캐시된 헬퍼) ─────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def ui_load_index_tickers(index_code: str) -> list[str]:
    """지수 구성종목 티커 리스트. FDR 호출 비용 있어 1시간 캐시."""
    if index_code == "^IXIC":
        return us_get_nasdaq_tickers()
    if index_code == "^GSPC":
        return us_get_sp500_tickers()
    if index_code == "KS11":
        return kr_get_kospi_tickers()
    if index_code == "KQ11":
        return kr_get_kosdaq_tickers()
    return []


@st.cache_data(ttl=300, show_spinner=False)
def ui_load_ranked_df(
    index_code: str,
    rs_period: int,
    top_n: int,
    filter_config: dict,
    _tickers_tuple: tuple[str, ...],  # 캐시 키 일부
) -> tuple[pd.DataFrame, dict]:
    """필터 + RS 랭킹을 한 번에 돌려 (ranked_df, stats) 반환.

    Args:
        index_code: `^IXIC` / `^GSPC`.
        rs_period: RS 기간(일).
        top_n: 상위 N개.
        filter_config: `screen_apply_filters` 에 넘길 dict.
        _tickers_tuple: 캐시 hash 용 (tuple 로 받아야 hashable).

    Returns:
        (ranked_df, stats). 빈 상태라도 DF 는 반환.
    """
    tickers = list(_tickers_tuple)
    if not tickers:
        return pd.DataFrame(), {"total": 0, "final": 0}

    df = screen_build_screening_df(tickers, lookback_days=20)
    filtered, stats = screen_apply_filters(df, filter_config)

    if filtered.empty:
        ranked = pd.DataFrame()
    else:
        ranked = screen_rank_rs(
            filtered.index.tolist(),
            index_code,
            period=rs_period,
            top_n=top_n,
        )
        # 메타(한글명/영문명/시가총액) 붙이기
        meta_cols = filtered[
            ["name_en", "name_kr", "avg_dollar_volume_20d", "market_cap"]
        ]
        if not ranked.empty:
            ranked = ranked.merge(
                meta_cols, left_on="ticker", right_index=True, how="left"
            )

    return ranked, stats


# ─── 렌더링 헬퍼 ────────────────────────────────────────────────────

_INDEX_DISPLAY = {
    "^IXIC": "나스닥",
    "^GSPC": "S&P 500",
    "^DJI": "다우",
    "KS11": "코스피",
    "KQ11": "코스닥",
}


def _index_display_name(index_code: str) -> str:
    """지수 코드를 사용자 친화 이름으로 변환. 매핑 없으면 원본 반환."""
    return _INDEX_DISPLAY.get(index_code, index_code)


def _sort_tickers_stale_first(tickers: list[str], normalize_upper: bool) -> list[str]:
    """캐시 마지막일이 오래된(또는 캐시 없는) 티커가 앞으로 오도록 정렬.

    `target = tickers[:limit]` 로 자르는 새로고침 흐름에서 stale 한 종목이
    먼저 갱신되도록 보장. 단순 알파벳 순으로는 같은 종목들만 매번 갱신되고
    나머지는 영구히 stale 상태로 남는 문제를 해결.

    Args:
        tickers: 원본 티커 리스트.
        normalize_upper: 미국 ticker 면 True (.upper()), 한국 6자리 코드면 False.

    Returns:
        정렬된 티커 리스트. 캐시 없는 종목 → 가장 먼저, 그 다음 last_date 오름차순.
    """
    last_dates = cache_get_all_last_price_dates()

    def key(t: str):
        lookup = t.upper() if normalize_upper else str(t)
        last = last_dates.get(lookup)
        # (캐시 있는가, 마지막일) — 캐시 없는 종목(False)이 가장 먼저.
        # 캐시 있는 경우는 last_date 오름차순 (오래된 게 먼저).
        return (last is not None, last or "")

    return sorted(tickers, key=key)


def _get_index_period_info(index_code: str, rs_period: int) -> dict | None:
    """지수 캐시에서 RS 산출 기준 정보(시작일/종료일/시작가/종료가/변화율) 추출.

    `_period_return` 과 동일한 인덱싱 (`s.iloc[-period-1]` ↔ `s.iloc[-1]`).
    데이터 부족 시 None 반환.
    """
    df = cache_load_index(index_code, days=rs_period + 10)
    if df is None or df.empty or "Close" not in df.columns:
        return None
    s = df["Close"].dropna()
    if len(s) < rs_period + 1:
        return None
    start_close = float(s.iloc[-rs_period - 1])
    end_close = float(s.iloc[-1])
    if start_close == 0:
        return None
    return {
        "start_date": s.index[-rs_period - 1].strftime("%Y-%m-%d"),
        "end_date": s.index[-1].strftime("%Y-%m-%d"),
        "start_close": start_close,
        "end_close": end_close,
        "return_pct": (end_close / start_close - 1.0) * 100.0,
    }


def _render_rs_header(
    index_code: str,
    index_display: str,
    rs_period: int,
    top_n: int,
) -> None:
    """헤더: 'RS Top N' 제목 + RS 산출 기준일/지수 변화 정보를 한 박스로 표시.

    오른쪽에 큰 글씨로 지수 N일 수익률, 작은 글씨로 시작일→종료일/시작가→종료가.
    """
    info = _get_index_period_info(index_code, rs_period)

    header_cols = st.columns([2, 1.4])
    with header_cols[0]:
        st.markdown(f"### RS Top {top_n}")
        st.caption(
            f"RS = (종목 {rs_period}일 수익률) / (지수 {rs_period}일 수익률)"
        )
    with header_cols[1]:
        if info is not None:
            sign = "+" if info["return_pct"] >= 0 else ""
            color = COLOR_PROFIT if info["return_pct"] >= 0 else COLOR_LOSS
            st.markdown(
                f"<div style='text-align:right;'>"
                f"<div style='color:{color}; font-weight:700; font-size:1.05rem;'>"
                f"{index_display} {rs_period}일 수익률: {sign}{info['return_pct']:.2f}%"
                f"</div>"
                f"<div style='color:{COLOR_MUTED}; font-size:0.78rem; margin-top:2px;'>"
                f"{info['start_date']} → {info['end_date']} "
                f"({info['start_close']:,.2f} → {info['end_close']:,.2f})"
                f"</div>"
                f"</div>",
                unsafe_allow_html=True,
            )


def render_asset_selector() -> str:
    """사이드바 최상단의 자산군 선택 UI.

    Returns: `"us"` / `"kr"` / `"crypto"` 중 하나.

    Streamlit 1.34+ 의 `st.pills` 사용. 선택 상태는 `scr_asset_class` 에 저장.
    """
    with st.sidebar:
        st.markdown("#### 주식 스크리닝")
        st.caption("상대강도(RS) 기반 종목 발굴")

        options = ["미국주식", "한국주식", "코인"]
        labels_to_code = {"미국주식": "us", "한국주식": "kr", "코인": "crypto"}

        # 세션 기본값
        current_label = st.session_state.get(
            f"{KEY_ASSET_CLASS}_label", "미국주식"
        )

        selected = st.pills(
            "자산군",
            options=options,
            default=current_label,
            label_visibility="collapsed",
            key=f"{KEY_ASSET_CLASS}_label",
        )
        # 선택 해제 방지
        if selected is None:
            selected = current_label

        code = labels_to_code.get(selected, "us")
        st.session_state[KEY_ASSET_CLASS] = code
        st.divider()
        return code


def _render_sidebar() -> tuple[str, int, int, int, dict]:
    """사이드바 렌더링 → (index_code, rs_period, top_n, refresh_limit, filter_config)."""
    with st.sidebar:
        st.markdown("##### 미국주식 설정")

        index_options = {
            "나스닥": "^IXIC",
            "S&P 500": "^GSPC",
        }
        selected_index_label = st.selectbox(
            "지수 선택",
            options=list(index_options.keys()),
            index=0,
            key=KEY_SELECTED_INDEX,
            help=(
                "RS 계산의 기준 지수. "
                "나스닥 = Yahoo Finance `^IXIC`, "
                "S&P 500 = `^GSPC`."
            ),
        )
        index_code = index_options[selected_index_label]

        rs_period = st.slider(
            "RS 계산 기간 (일)",
            min_value=5,
            max_value=60,
            value=20,
            step=1,
            key=KEY_RS_PERIOD,
            help="RS = (종목 N일 수익률) / (지수 N일 수익률)",
        )

        top_n = st.slider(
            "표시 개수 (Top N)",
            min_value=10,
            max_value=50,
            value=20,
            step=5,
            key=KEY_TOP_N,
            help="랭킹 테이블에 표시할 상위 종목 수.",
        )

        # 지수 캐시 상태를 작게 표시
        idx_cache = cache_load_index(index_code, days=5)
        idx_cached = idx_cache is not None and not idx_cache.empty
        badge_color = "#1a9cff" if idx_cached else "#ff9500"
        badge_text = "데이터 준비됨" if idx_cached else "데이터 없음"
        st.markdown(
            f"<div style='font-size:0.78rem; color:{COLOR_MUTED}; margin-top:-4px;'>"
            f"지수 상태: <span style='color:{badge_color}; font-weight:600;'>"
            f"{badge_text}</span></div>",
            unsafe_allow_html=True,
        )

        # ─── 데이터 새로고침 ───
        st.divider()
        st.markdown("##### 데이터 새로고침")
        refresh_limit = st.number_input(
            "이번에 받을 종목 수",
            min_value=10,
            max_value=4000,
            value=200,
            step=50,
            key=KEY_REFRESH_LIMIT,
            help=(
                "yfinance 에서 한 번에 받아올 종목 수. "
                "나스닥 전체(3800+)는 30분 이상 걸림. "
                "테스트/점진 확장용으로 제한 가능."
            ),
        )
        force_refresh = st.checkbox(
            "캐시 무시하고 전부 새로 받기 (force)",
            value=False,
            key="scr_us_force_refresh",
            help=(
                "이전 캐시를 덮어쓰고 yfinance 에서 다시 받음. 분할/spin-off 등 "
                "corporate action 이후 historical 가격이 retroactively 재조정된 "
                "경우 이 옵션으로 정합성 복구."
            ),
        )
        refresh_clicked = st.button(
            "yfinance에서 내려받기",
            width="stretch",
            help=(
                "지수 + 선두 N개 구성종목의 시세/메타를 yfinance 에서 내려받아 "
                "로컬 SQLite 에 저장합니다. 앱은 이 DB만 읽으므로 최신 시세를 "
                "반영하려면 이 버튼을 눌러야 합니다."
            ),
        )
        if refresh_clicked:
            _run_refresh(index_code, int(refresh_limit), force=bool(force_refresh))

        # ─── 필터 설정 ───
        st.divider()
        with st.expander("필터 설정", expanded=False):
            min_price = st.number_input(
                "최소 주가 ($)",
                min_value=0.0,
                max_value=10_000.0,
                value=10.0,
                step=1.0,
                key=KEY_FILTER_MIN_PRICE,
            )
            min_dollar_vol_m = st.number_input(
                "최소 평균 거래대금 (백만 $)",
                min_value=0.0,
                max_value=10_000.0,
                value=20.0,
                step=5.0,
                key=KEY_FILTER_MIN_DOLLAR_VOL_M,
                help="20일 평균 일 거래대금. 20M ≈ 300억 원.",
            )
            max_range_pct = st.slider(
                "최근 20일 최대 일일 변동폭 한도 (%)",
                min_value=10,
                max_value=100,
                value=50,
                step=5,
                key=KEY_FILTER_MAX_RANGE_PCT,
                help="이 값 이상 변동한 날이 있는 종목은 제외.",
            )
            exclude_china = st.checkbox(
                "중국기업 제외",
                value=True,
                key=KEY_FILTER_EXCLUDE_CHINA,
            )
            exclude_risk = st.checkbox(
                "관리/위험종목 제외",
                value=True,
                key=KEY_FILTER_EXCLUDE_RISK,
            )

        filter_config = {
            "min_price": float(min_price),
            "min_dollar_volume": float(min_dollar_vol_m) * 1_000_000.0,
            "max_daily_range_pct": float(max_range_pct) / 100.0,
            "lookback_days": 20,
            "exclude_china": bool(exclude_china),
            "exclude_risk": bool(exclude_risk),
        }

    return index_code, int(rs_period), int(top_n), int(refresh_limit), filter_config


def _run_refresh(index_code: str, limit: int, force: bool = False) -> None:
    """캐시 새로고침 — 지수 + 구성종목 상위 limit 개의 시세/메타 갱신.

    Args:
        force: True 면 캐시 무시하고 전체 재로드 (corporate action 정합성 복구).
    """
    label = f"{index_code} 캐시 새로고침 시작 …"
    if force:
        label = f"{index_code} 강제 새로고침 (캐시 덮어쓰기) …"
    with st.status(label, expanded=True) as status:
        try:
            st.write("1) 구성종목 리스트 로드 + stale 우선 정렬")
            tickers = ui_load_index_tickers(index_code)
            if not tickers:
                status.update(label="구성종목을 가져오지 못함", state="error")
                return
            # 캐시 마지막일이 오래된 종목 우선 (stale starvation 방지)
            tickers = _sort_tickers_stale_first(tickers, normalize_upper=True)
            target = tickers[:limit]
            st.write(
                f"   → 총 {len(tickers)}개 중 선두(stale 우선) {len(target)}개 대상"
                + (" · force=True" if force else "")
            )

            st.write("2) 지수 시세 갱신")
            idx_result = screen_refresh_index(index_code, days=300, force=force)
            st.write(f"   → {idx_result}")

            st.write(f"3) 종목 시세 갱신 (sleep 0.2s/건 — {len(target)}건)")
            with st.spinner("yfinance 호출 중..."):
                px_result = screen_refresh_prices(
                    target, days=300, force=force, sleep_sec=0.2
                )
            st.write(
                f"   → updated={px_result['updated']}, "
                f"skipped={px_result['skipped']}, "
                f"failed={len(px_result['failed'])}"
            )

            st.write(f"4) 메타데이터 갱신 (sleep 0.3s/건 — {len(target)}건)")
            with st.spinner("yfinance Ticker.info 호출 중..."):
                meta_result = screen_refresh_meta(
                    target, ttl_days=7, force=force, sleep_sec=0.3
                )
            st.write(
                f"   → updated={meta_result['updated']}, "
                f"skipped={meta_result['skipped']}, "
                f"failed={len(meta_result['failed'])}"
            )

            # UI 캐시도 비워서 새 데이터가 반영되도록
            ui_load_ranked_df.clear()
            status.update(label="새로고침 완료", state="complete")
        except Exception as e:
            status.update(label=f"새로고침 실패: {e}", state="error")


def _render_pipeline_badge(stats: dict, ranked_len: int) -> None:
    """필터 축소 흐름 배지 — '3500 → 2800 → ... → 800 → Top N'.

    `after_market_cap` 단계는 stats 에 있을 때만(시가총액 필터 적용) 표시.
    """
    total = stats.get("total", 0)
    if total == 0:
        return
    parts = [
        f"전체 {total}",
        f"주가 {stats.get('after_price', 0)}",
        f"거래대금 {stats.get('after_volume', 0)}",
    ]
    # 시가총액 필터가 실제로 줄였을 때만 단계 추가 (미국 탭은 0이라 생략)
    after_mc = stats.get("after_market_cap")
    if after_mc is not None and after_mc != stats.get("after_volume"):
        parts.append(f"시총 {after_mc}")
    parts.extend([
        f"관리 {stats.get('after_risk', 0)}",
        f"중국 {stats.get('after_china', 0)}",
        f"변동성 {stats.get('after_volatility', 0)}",
        f"Top {ranked_len}",
    ])
    st.caption(" → ".join(parts))


def _style_return_col(val: float) -> str:
    """return_n (소수) 을 수익=빨강 / 손실=파랑 으로 색칠. NaN 은 무색."""
    if pd.isna(val):
        return ""
    if val > 0:
        return f"color: {COLOR_PROFIT}; font-weight: 600;"
    if val < 0:
        return f"color: {COLOR_LOSS}; font-weight: 600;"
    return ""


def _render_ranking_table(
    ranked: pd.DataFrame,
    rs_period: int,
) -> str | None:
    """랭킹 테이블 렌더링 + 선택된 티커 반환(없으면 None)."""
    if ranked.empty:
        return None

    # 화면용 가공
    # 수익률은 소수(1.05 = 105%) → % 단위로 100배 변환 후 NumberColumn 의 '%+.2f%%' 포맷이 의도대로 동작
    display = pd.DataFrame(
        {
            "순위": ranked["rank"],
            "티커": ranked["ticker"],
            "종목명": ranked.apply(
                lambda r: r.get("name_kr") or r.get("name_en") or r["ticker"],
                axis=1,
            ),
            "현재가": ranked["last_price"],
            "RS": ranked["rs"],
            f"{rs_period}일 수익률": ranked["return_n"] * 100.0,
            "거래대금(M$)": (
                ranked["avg_dollar_volume_20d"] / 1_000_000.0
                if "avg_dollar_volume_20d" in ranked.columns
                else pd.Series([float("nan")] * len(ranked))
            ),
        }
    )

    # 수익률 색상을 위해 Styler 사용하고 싶지만,
    # st.dataframe(selection_mode=...) 은 DataFrame 만 받으므로
    # column_config 포맷 + CSS 로 대체.
    event = st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        height=min(600, 45 + 35 * len(display)),
        on_select="rerun",
        selection_mode="single-row",
        key=KEY_SELECTED_ROW,
        column_config={
            "순위": st.column_config.NumberColumn(width="small"),
            "티커": st.column_config.TextColumn(width="small"),
            "종목명": st.column_config.TextColumn(width="medium"),
            "현재가": st.column_config.NumberColumn(format="$%.2f"),
            "RS": st.column_config.NumberColumn(format="%.3f"),
            f"{rs_period}일 수익률": st.column_config.NumberColumn(format="%+.2f%%"),
            "거래대금(M$)": st.column_config.NumberColumn(format="%.1f"),
        },
    )

    # 선택된 행에서 티커 추출
    selected_rows = event.selection.rows if hasattr(event, "selection") else []
    if selected_rows:
        idx = selected_rows[0]
        if 0 <= idx < len(ranked):
            return str(ranked.iloc[idx]["ticker"])
    return None


def _render_filter_summary(filter_config: dict) -> None:
    """현재 필터 조건을 한 줄 배지로."""
    badges = [
        f"주가 ≥ ${filter_config['min_price']:.0f}",
        f"거래대금 ≥ ${filter_config['min_dollar_volume']/1_000_000:.0f}M",
        f"변동폭 < {filter_config['max_daily_range_pct']*100:.0f}%",
    ]
    if filter_config.get("exclude_china"):
        badges.append("중국 제외")
    if filter_config.get("exclude_risk"):
        badges.append("관리 제외")
    st.caption("필터: " + " · ".join(badges))


# ─── 차트 패널 (Phase 1.7) ──────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def ui_load_chart_df(ticker: str, days: int) -> pd.DataFrame:
    """차트용 시세 로드 (캐시). 티커 전환 쾌적용."""
    return cache_load_prices(ticker, days=days)


def _calc_wilder_atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 9
) -> pd.Series:
    """Wilder's ATR.

    TR_t  = max(H-L, |H - prevC|, |L - prevC|)
    ATR_t = (ATR_{t-1} * (period - 1) + TR_t) / period
    초기값: 첫 `period` 일의 단순평균으로 부트스트랩.

    Wilder 방식을 택한 이유: 원조 공식이자 업계 표준. 단순 SMA(TR) 보다
    최근 변동성 반영이 빠르고 과거 값이 완만하게 감쇠해 추세 전환 구간에서도
    안정적.
    """
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = pd.Series(np.nan, index=tr.index, dtype=float)
    if len(tr) < period:
        return atr

    # period 째 위치(0-indexed: period-1)에 SMA(TR[0:period]) 부트스트랩
    initial = tr.iloc[1 : period + 1].mean()  # 첫 TR은 NaN, 이후 period 개 평균
    atr.iloc[period] = initial
    for i in range(period + 1, len(tr)):
        prev_atr = atr.iloc[i - 1]
        tr_i = tr.iloc[i]
        if pd.isna(prev_atr) or pd.isna(tr_i):
            continue
        atr.iloc[i] = (prev_atr * (period - 1) + tr_i) / period
    return atr


def _us_render_chart(ticker: str, lookback_days: int = 120) -> None:
    """선택된 티커의 캔들 + 5MA + 9ATR 차트."""
    # 지표 계산 여유를 위해 +10
    df = ui_load_chart_df(ticker, days=lookback_days + 10)

    if df is None or len(df) < 15:
        st.warning(
            f"**{ticker}** 차트를 그릴 데이터가 부족합니다 "
            f"(현재 {0 if df is None else len(df)}행, 15행 이상 필요). "
            "사이드바의 **[yfinance에서 내려받기]** 을 실행해주세요."
        )
        return

    # 지표
    ma5 = df["Close"].rolling(5).mean()
    atr9 = _calc_wilder_atr(df["High"], df["Low"], df["Close"], period=9)

    # 표시 구간은 lookback_days 만큼 잘라내지만 지표 값은 이미 충분히 워밍업된 상태
    df_view = df.tail(lookback_days)
    ma5_view = ma5.reindex(df_view.index)
    atr9_view = atr9.reindex(df_view.index)

    last_close = float(df_view["Close"].iloc[-1])
    last_date = df_view.index[-1].strftime("%Y-%m-%d")
    title = f"{ticker} · ${last_close:.2f} ({last_date})"

    # ─── Plotly 서브플롯 (2행) ───
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.7, 0.3],
        vertical_spacing=0.05,
        subplot_titles=("", "9-day ATR (Wilder)"),
    )

    # 캔들
    fig.add_trace(
        go.Candlestick(
            x=df_view.index,
            open=df_view["Open"],
            high=df_view["High"],
            low=df_view["Low"],
            close=df_view["Close"],
            name="OHLC",
            increasing_line_color=_COLOR_UP,
            increasing_fillcolor=_COLOR_UP,
            decreasing_line_color=_COLOR_DOWN,
            decreasing_fillcolor=_COLOR_DOWN,
            showlegend=False,
        ),
        row=1,
        col=1,
    )

    # 5일 이평선
    fig.add_trace(
        go.Scatter(
            x=df_view.index,
            y=ma5_view,
            name="MA5",
            line=dict(color=_COLOR_MA, width=1.8),
            hovertemplate="MA5: $%{y:.2f}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    # 9일 ATR (음영)
    fig.add_trace(
        go.Scatter(
            x=df_view.index,
            y=atr9_view,
            name="ATR9",
            line=dict(color=_COLOR_ATR, width=1.5),
            fill="tozeroy",
            fillcolor=_COLOR_ATR_FILL,
            hovertemplate="ATR9: $%{y:.2f}<extra></extra>",
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    # 주말 갭 제거
    rangebreaks = [dict(bounds=["sat", "mon"])]

    fig.update_layout(
        title=dict(text=title, x=0.01, xanchor="left", font=dict(size=15, color=COLOR_TEXT)),
        height=620,
        margin=dict(l=10, r=10, t=50, b=10),
        paper_bgcolor=COLOR_CARD,
        plot_bgcolor=COLOR_CARD,
        font=dict(color=COLOR_TEXT),
        xaxis=dict(rangeslider=dict(visible=False), rangebreaks=rangebreaks),
        xaxis2=dict(rangebreaks=rangebreaks),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=COLOR_MUTED, size=11),
        ),
        hovermode="x unified",
    )

    # 축 스타일 (라이트 테마용 — 연한 회색 격자)
    grid_color = COLOR_BORDER
    fig.update_xaxes(
        showgrid=True, gridcolor=grid_color, zeroline=False,
        tickfont=dict(color=COLOR_MUTED), linecolor=COLOR_BORDER,
    )
    fig.update_yaxes(
        showgrid=True, gridcolor=grid_color, zeroline=False,
        linecolor=COLOR_BORDER,
    )
    fig.update_yaxes(title_text="Price ($)", row=1, col=1, tickfont=dict(color=COLOR_MUTED))
    fig.update_yaxes(title_text="ATR", row=2, col=1, tickfont=dict(color=COLOR_MUTED))

    st.plotly_chart(fig, width="stretch", theme=None)

    # ─── 하단 미니 요약 ───
    _render_chart_metrics(df, atr9)


def _render_chart_metrics(df: pd.DataFrame, atr9: pd.Series) -> None:
    """차트 하단 3칸 메트릭: ATR 절대값/대비%, 5일 수익률, 20일 평균 거래대금."""
    last_close = float(df["Close"].iloc[-1])

    # 현재 ATR
    atr_last = atr9.dropna()
    if len(atr_last) > 0:
        atr_val = float(atr_last.iloc[-1])
        atr_pct = (atr_val / last_close * 100.0) if last_close > 0 else 0.0
        atr_display = f"${atr_val:.2f}"
        atr_delta = f"{atr_pct:.2f}% of close"
    else:
        atr_display = "—"
        atr_delta = ""

    # 최근 5일 수익률 (6개 close 필요: t와 t-5)
    if len(df) >= 6:
        ret_5d = (df["Close"].iloc[-1] / df["Close"].iloc[-6] - 1.0) * 100.0
        ret_display = f"{ret_5d:+.2f}%"
    else:
        ret_display = "—"

    # 최근 20일 평균 거래대금 (백만$)
    dv = df.get("dollar_volume")
    if dv is not None and dv.dropna().shape[0] > 0:
        avg_dv_m = float(dv.tail(20).mean()) / 1_000_000.0
        dv_display = f"${avg_dv_m:,.1f}M"
    else:
        dv_display = "—"

    c1, c2, c3 = st.columns(3)
    c1.metric("9-day ATR", atr_display, atr_delta, delta_color="off")
    c2.metric("5일 수익률", ret_display)
    c3.metric("거래대금(20D 평균)", dv_display)


# ─── 퍼블릭 엔트리 ─────────────────────────────────────────────────

def render_us_tab() -> None:
    """미국주식 스크리닝 탭."""
    index_code, rs_period, top_n, _refresh_limit, filter_config = _render_sidebar()

    # 지수 수익률 해석 경고를 위해 stats 와 랭킹 모두 확보
    tickers = ui_load_index_tickers(index_code)
    ranked, stats = ui_load_ranked_df(
        index_code=index_code,
        rs_period=rs_period,
        top_n=top_n,
        filter_config=filter_config,
        _tickers_tuple=tuple(tickers),
    )

    # 지수 수익률 배지 (해석 주의용)
    idx_return = None
    if not ranked.empty and "index_return_n" in ranked.columns:
        idx_return = float(ranked["index_return_n"].iloc[0])

    col_left, col_right = st.columns([1.2, 1], gap="large")

    with col_left:
        index_display = _index_display_name(index_code)
        _render_rs_header(index_code, index_display, rs_period, top_n)

        _render_filter_summary(filter_config)
        _render_pipeline_badge(stats, len(ranked))

        # ─── 빈 상태 분기 ───
        if stats.get("total", 0) == 0 or not tickers:
            st.warning(
                f"**{index_display}** 구성종목 데이터가 캐시에 없습니다. "
                "사이드바의 **[yfinance에서 내려받기]** 버튼을 눌러 "
                "데이터를 먼저 받아주세요."
            )
            return

        if stats.get("final", 0) == 0:
            st.warning(
                "필터 조건에 맞는 종목이 없습니다. "
                "사이드바의 **필터 설정** 을 완화해보세요."
            )
            return

        if ranked.empty:
            # final > 0 인데 ranked 가 비었다 = 지수 데이터 부재 or 지수 flat
            idx_cache = cache_load_index(index_code, days=rs_period + 10)
            if idx_cache is None or idx_cache.empty or len(idx_cache) < rs_period + 1:
                st.warning(
                    f"**{index_display}** 지수 시세가 캐시에 없거나 부족합니다. "
                    "사이드바에서 이 지수를 선택한 상태로 "
                    "**[yfinance에서 내려받기]** 를 눌러 지수 데이터를 받아주세요."
                )
            else:
                st.warning(
                    f"{index_display} {rs_period}일 변동폭이 너무 작아 "
                    "RS 계산이 불가합니다. 기간을 늘려보세요."
                )
            return

        # ─── 지수 수익률 음수 경고 ───
        if idx_return is not None and idx_return < 0:
            st.info(
                "⚠️ 기준 지수 수익률이 **음수**입니다. "
                "이때 RS는 '지수보다 덜 떨어졌거나 더 오른 종목'을 의미하며, "
                "양수 장에서의 RS 해석과 반대가 될 수 있습니다."
            )

        selected_ticker = _render_ranking_table(ranked, rs_period)
        if selected_ticker is not None:
            st.session_state[KEY_SELECTED_TICKER] = selected_ticker

    with col_right:
        st.markdown("### 차트 패널")
        selected = st.session_state.get(KEY_SELECTED_TICKER)
        if selected:
            _us_render_chart(str(selected), lookback_days=120)
        else:
            st.info(
                "좌측 테이블에서 종목을 선택하면 "
                "캔들스틱 + 5일 이평선 + 9일 ATR 차트가 표시됩니다."
            )


# ─── 한국주식 전용 헬퍼 ────────────────────────────────────────────────

def _render_sidebar_kr() -> tuple[str, int, int, int, dict]:
    """한국주식 사이드바 → (index_code, rs_period, top_n, refresh_limit, filter_config)."""
    with st.sidebar:
        st.markdown("##### 한국주식 설정")

        index_options = {"코스피": "KS11", "코스닥": "KQ11"}
        selected_index_label = st.selectbox(
            "지수 선택",
            options=list(index_options.keys()),
            index=0,
            key=KEY_KR_SELECTED_INDEX,
            help="RS 계산 기준. 코스피 = `KS11`, 코스닥 = `KQ11` (FinanceDataReader).",
        )
        index_code = index_options[selected_index_label]

        rs_period = st.slider(
            "RS 계산 기간 (일)",
            min_value=5,
            max_value=60,
            value=20,
            step=1,
            key=KEY_KR_RS_PERIOD,
            help="RS = (종목 N일 수익률) / (지수 N일 수익률)",
        )

        top_n = st.slider(
            "표시 개수 (Top N)",
            min_value=10,
            max_value=50,
            value=20,
            step=5,
            key=KEY_KR_TOP_N,
            help="랭킹 테이블에 표시할 상위 종목 수.",
        )

        # 지수 캐시 상태
        idx_cache = cache_load_index(index_code, days=5)
        idx_cached = idx_cache is not None and not idx_cache.empty
        badge_color = "#1a9cff" if idx_cached else "#ff9500"
        badge_text = "데이터 준비됨" if idx_cached else "데이터 없음"
        st.markdown(
            f"<div style='font-size:0.78rem; color:{COLOR_MUTED}; margin-top:-4px;'>"
            f"지수 상태: <span style='color:{badge_color}; font-weight:600;'>"
            f"{badge_text}</span></div>",
            unsafe_allow_html=True,
        )

        # ─── 데이터 새로고침 ───
        st.divider()
        st.markdown("##### 데이터 새로고침")
        refresh_limit = st.number_input(
            "이번에 받을 종목 수",
            min_value=10,
            max_value=2900,
            value=200,
            step=50,
            key=KEY_KR_REFRESH_LIMIT,
            help=(
                "FinanceDataReader 에서 한 번에 받아올 종목 수. "
                "코스피 전체(950)는 5분, 코스닥 전체(1800)는 10분 안팎."
            ),
        )
        force_refresh = st.checkbox(
            "캐시 무시하고 전부 새로 받기 (force)",
            value=False,
            key="scr_kr_force_refresh",
            help=(
                "이전 캐시를 덮어쓰고 FDR 에서 다시 받음. 분할/액면분할 등 이후 "
                "historical 가격이 retroactively 재조정된 경우 정합성 복구용."
            ),
        )
        refresh_clicked = st.button(
            "FDR에서 내려받기",
            width="stretch",
            help=(
                "지수 + 선두 N개 구성종목의 시세/메타를 FinanceDataReader 에서 "
                "내려받아 로컬 SQLite 에 저장합니다."
            ),
        )
        if refresh_clicked:
            _run_refresh_kr(index_code, int(refresh_limit), force=bool(force_refresh))

        # ─── 필터 설정 ───
        st.divider()
        with st.expander("필터 설정", expanded=False):
            min_price = st.number_input(
                "최소 주가 (원)",
                min_value=0,
                max_value=10_000_000,
                value=1_000,
                step=100,
                key=KEY_KR_FILTER_MIN_PRICE,
                help="동전주(주가가 너무 낮은 종목) 배제.",
            )
            min_amount_e = st.number_input(
                "최소 평균 거래대금 (억 원)",
                min_value=0,
                max_value=100_000,
                value=300,
                step=50,
                key=KEY_KR_FILTER_MIN_AMOUNT_E,
                help="20일 평균 일 거래대금. 한국주식 기본 기준 = 300억 원.",
            )
            min_marketcap_e = st.number_input(
                "최소 시가총액 (억 원)",
                min_value=0,
                max_value=10_000_000,
                value=3_000,
                step=500,
                key=KEY_KR_FILTER_MIN_MARKETCAP_E,
                help="시가총액이 너무 작은 종목 배제. 사용자 결정 기본 3,000억.",
            )
            max_range_pct = st.slider(
                "최근 20일 최대 일일 변동폭 한도 (%)",
                min_value=10,
                max_value=100,
                value=50,
                step=5,
                key=KEY_KR_FILTER_MAX_RANGE_PCT,
                help="이 값 이상 변동한 날이 있는 종목은 제외.",
            )
            exclude_risk = st.checkbox(
                "관리/위험종목 제외",
                value=True,
                key=KEY_KR_FILTER_EXCLUDE_RISK,
                help=(
                    "KRX 공시 기반 관리종목/투자주의/거래정지 제외. "
                    "위험종목 데이터를 사이드바 새로고침에서 갱신해야 효과가 적용됩니다."
                ),
            )
            st.caption(
                "✓ 모집단 단계에서 우선주/리츠/ETF/스팩/외국기업은 자동 제외됨"
            )

        filter_config = {
            "min_price": float(min_price),
            "min_dollar_volume": float(min_amount_e) * 100_000_000.0,    # 억원 → 원
            "min_market_cap": float(min_marketcap_e) * 100_000_000.0,    # 억원 → 원
            "max_daily_range_pct": float(max_range_pct) / 100.0,
            "lookback_days": 20,
            "exclude_china": False,       # 외국기업은 모집단 단계에서 이미 제거
            "exclude_risk": bool(exclude_risk),
        }

    return index_code, int(rs_period), int(top_n), int(refresh_limit), filter_config


def _run_refresh_kr(index_code: str, limit: int, force: bool = False) -> None:
    """한국주식 캐시 새로고침 — 지수 + 구성종목 상위 limit 개의 시세/메타.

    Args:
        force: True 면 캐시 무시하고 전체 재로드.
    """
    label = f"{index_code} 캐시 새로고침 시작 …"
    if force:
        label = f"{index_code} 강제 새로고침 (캐시 덮어쓰기) …"
    with st.status(label, expanded=True) as status:
        try:
            st.write("1) 구성종목 리스트 로드 + stale 우선 정렬")
            tickers = ui_load_index_tickers(index_code)
            if not tickers:
                status.update(label="구성종목을 가져오지 못함", state="error")
                return
            # 캐시 마지막일이 오래된 종목 우선 (stale starvation 방지)
            tickers = _sort_tickers_stale_first(tickers, normalize_upper=False)
            target = tickers[:limit]
            st.write(
                f"   → 총 {len(tickers)}개 중 선두(stale 우선) {len(target)}개 대상"
                + (" · force=True" if force else "")
            )

            st.write("2) 지수 시세 갱신")
            idx_result = screen_refresh_index_kr(index_code, days=300, force=force)
            st.write(f"   → {idx_result}")

            st.write(f"3) 종목 시세 갱신 ({len(target)}건, sleep 0.1s/건)")
            with st.spinner("FDR 호출 중..."):
                px_result = screen_refresh_prices_kr(
                    target, days=300, force=force, sleep_sec=0.1
                )
            st.write(
                f"   → updated={px_result['updated']}, "
                f"skipped={px_result['skipped']}, "
                f"failed={len(px_result['failed'])}"
            )

            st.write(f"4) 메타데이터 갱신 ({len(target)}건)")
            with st.spinner("FDR StockListing 조회 중..."):
                meta_result = screen_refresh_meta_kr(
                    target, ttl_days=7, force=force
                )
            st.write(
                f"   → updated={meta_result['updated']}, "
                f"skipped={meta_result['skipped']}, "
                f"failed={len(meta_result['failed'])}"
            )

            ui_load_ranked_df.clear()
            status.update(label="새로고침 완료", state="complete")
        except Exception as e:
            status.update(label=f"새로고침 실패: {e}", state="error")


def _render_ranking_table_kr(
    ranked: pd.DataFrame, rs_period: int
) -> str | None:
    """한국주식 랭킹 테이블 (원화 표기). 선택된 티커 반환."""
    if ranked.empty:
        return None

    # 수익률은 소수(1.05 = 105%) → % 단위로 100배 변환
    display = pd.DataFrame(
        {
            "순위": ranked["rank"],
            "코드": ranked["ticker"],
            "종목명": ranked.apply(
                lambda r: r.get("name_kr") or r.get("name_en") or r["ticker"],
                axis=1,
            ),
            "현재가": ranked["last_price"],
            "RS": ranked["rs"],
            f"{rs_period}일 수익률": ranked["return_n"] * 100.0,
            "시총(억)": (
                ranked["market_cap"] / 100_000_000.0
                if "market_cap" in ranked.columns
                else pd.Series([float("nan")] * len(ranked))
            ),
            "거래대금(억)": (
                ranked["avg_dollar_volume_20d"] / 100_000_000.0
                if "avg_dollar_volume_20d" in ranked.columns
                else pd.Series([float("nan")] * len(ranked))
            ),
        }
    )

    event = st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        height=min(600, 45 + 35 * len(display)),
        on_select="rerun",
        selection_mode="single-row",
        key=KEY_KR_SELECTED_ROW,
        column_config={
            "순위": st.column_config.NumberColumn(width="small"),
            "코드": st.column_config.TextColumn(width="small"),
            "종목명": st.column_config.TextColumn(width="medium"),
            "현재가": st.column_config.NumberColumn(format="₩%,d"),
            "RS": st.column_config.NumberColumn(format="%.3f"),
            f"{rs_period}일 수익률": st.column_config.NumberColumn(format="%+.2f%%"),
            "시총(억)": st.column_config.NumberColumn(format="%,.0f"),
            "거래대금(억)": st.column_config.NumberColumn(format="%,.0f"),
        },
    )

    selected_rows = event.selection.rows if hasattr(event, "selection") else []
    if selected_rows:
        idx = selected_rows[0]
        if 0 <= idx < len(ranked):
            return str(ranked.iloc[idx]["ticker"])
    return None


def _render_filter_summary_kr(filter_config: dict) -> None:
    """한국 필터 조건 한 줄 배지 (원화)."""
    badges = [
        f"주가 ≥ {filter_config['min_price']:,.0f}원",
        f"거래대금 ≥ {filter_config['min_dollar_volume']/100_000_000:,.0f}억",
    ]
    min_mc = filter_config.get("min_market_cap", 0)
    if min_mc > 0:
        badges.append(f"시총 ≥ {min_mc/100_000_000:,.0f}억")
    badges.append(f"변동폭 < {filter_config['max_daily_range_pct']*100:.0f}%")
    if filter_config.get("exclude_risk"):
        badges.append("관리 제외*")  # * = 데이터 미적용일 수 있음
    st.caption("필터: " + " · ".join(badges))


def _kr_render_chart(ticker: str, lookback_days: int = 120) -> None:
    """한국주식 차트 — 미국 차트와 동일 구조, 가격 표기만 원화."""
    df = ui_load_chart_df(ticker, days=lookback_days + 10)

    if df is None or len(df) < 15:
        st.warning(
            f"**{ticker}** 차트를 그릴 데이터가 부족합니다 "
            f"(현재 {0 if df is None else len(df)}행, 15행 이상 필요). "
            "사이드바의 **[FDR에서 내려받기]** 를 실행해주세요."
        )
        return

    ma5 = df["Close"].rolling(5).mean()
    atr9 = _calc_wilder_atr(df["High"], df["Low"], df["Close"], period=9)

    df_view = df.tail(lookback_days)
    ma5_view = ma5.reindex(df_view.index)
    atr9_view = atr9.reindex(df_view.index)

    last_close = float(df_view["Close"].iloc[-1])
    last_date = df_view.index[-1].strftime("%Y-%m-%d")
    title = f"{ticker} · ₩{last_close:,.0f} ({last_date})"

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.7, 0.3],
        vertical_spacing=0.05,
        subplot_titles=("", "9-day ATR (Wilder)"),
    )

    fig.add_trace(
        go.Candlestick(
            x=df_view.index,
            open=df_view["Open"],
            high=df_view["High"],
            low=df_view["Low"],
            close=df_view["Close"],
            name="OHLC",
            increasing_line_color=_COLOR_UP,
            increasing_fillcolor=_COLOR_UP,
            decreasing_line_color=_COLOR_DOWN,
            decreasing_fillcolor=_COLOR_DOWN,
            showlegend=False,
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df_view.index, y=ma5_view, name="MA5",
            line=dict(color=_COLOR_MA, width=1.8),
            hovertemplate="MA5: ₩%{y:,.0f}<extra></extra>",
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df_view.index, y=atr9_view, name="ATR9",
            line=dict(color=_COLOR_ATR, width=1.5),
            fill="tozeroy", fillcolor=_COLOR_ATR_FILL,
            hovertemplate="ATR9: ₩%{y:,.0f}<extra></extra>",
            showlegend=False,
        ),
        row=2, col=1,
    )

    rangebreaks = [dict(bounds=["sat", "mon"])]
    fig.update_layout(
        title=dict(text=title, x=0.01, xanchor="left", font=dict(size=15, color=COLOR_TEXT)),
        height=620,
        margin=dict(l=10, r=10, t=50, b=10),
        paper_bgcolor=COLOR_CARD,
        plot_bgcolor=COLOR_CARD,
        font=dict(color=COLOR_TEXT),
        xaxis=dict(rangeslider=dict(visible=False), rangebreaks=rangebreaks),
        xaxis2=dict(rangebreaks=rangebreaks),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
            bgcolor="rgba(0,0,0,0)", font=dict(color=COLOR_MUTED, size=11),
        ),
        hovermode="x unified",
    )
    fig.update_xaxes(
        showgrid=True, gridcolor=COLOR_BORDER, zeroline=False,
        tickfont=dict(color=COLOR_MUTED), linecolor=COLOR_BORDER,
    )
    fig.update_yaxes(
        showgrid=True, gridcolor=COLOR_BORDER, zeroline=False,
        linecolor=COLOR_BORDER,
    )
    fig.update_yaxes(title_text="Price (₩)", row=1, col=1, tickfont=dict(color=COLOR_MUTED))
    fig.update_yaxes(title_text="ATR", row=2, col=1, tickfont=dict(color=COLOR_MUTED))

    st.plotly_chart(fig, width="stretch", theme=None)

    _render_chart_metrics_kr(df, atr9)


def _render_chart_metrics_kr(df: pd.DataFrame, atr9: pd.Series) -> None:
    """한국주식 차트 하단 3칸 메트릭 (원화)."""
    last_close = float(df["Close"].iloc[-1])

    atr_last = atr9.dropna()
    if len(atr_last) > 0:
        atr_val = float(atr_last.iloc[-1])
        atr_pct = (atr_val / last_close * 100.0) if last_close > 0 else 0.0
        atr_display = f"₩{atr_val:,.0f}"
        atr_delta = f"{atr_pct:.2f}% of close"
    else:
        atr_display = "—"
        atr_delta = ""

    if len(df) >= 6:
        ret_5d = (df["Close"].iloc[-1] / df["Close"].iloc[-6] - 1.0) * 100.0
        ret_display = f"{ret_5d:+.2f}%"
    else:
        ret_display = "—"

    dv = df.get("dollar_volume")
    if dv is not None and dv.dropna().shape[0] > 0:
        avg_dv_e = float(dv.tail(20).mean()) / 100_000_000.0
        dv_display = f"{avg_dv_e:,.0f}억"
    else:
        dv_display = "—"

    c1, c2, c3 = st.columns(3)
    c1.metric("9-day ATR", atr_display, atr_delta, delta_color="off")
    c2.metric("5일 수익률", ret_display)
    c3.metric("거래대금(20D 평균)", dv_display)


def render_kr_tab() -> None:
    """한국주식 스크리닝 탭 (Phase 2)."""
    index_code, rs_period, top_n, _refresh_limit, filter_config = _render_sidebar_kr()

    tickers = ui_load_index_tickers(index_code)
    ranked, stats = ui_load_ranked_df(
        index_code=index_code,
        rs_period=rs_period,
        top_n=top_n,
        filter_config=filter_config,
        _tickers_tuple=tuple(tickers),
    )

    idx_return = None
    if not ranked.empty and "index_return_n" in ranked.columns:
        idx_return = float(ranked["index_return_n"].iloc[0])

    col_left, col_right = st.columns([1.2, 1], gap="large")

    with col_left:
        index_display = _index_display_name(index_code)
        _render_rs_header(index_code, index_display, rs_period, top_n)

        _render_filter_summary_kr(filter_config)
        _render_pipeline_badge(stats, len(ranked))

        if stats.get("total", 0) == 0 or not tickers:
            st.warning(
                f"**{index_display}** 구성종목 데이터가 캐시에 없습니다. "
                "사이드바의 **[FDR에서 내려받기]** 버튼을 눌러 "
                "데이터를 먼저 받아주세요."
            )
            return

        if stats.get("final", 0) == 0:
            st.warning(
                "필터 조건에 맞는 종목이 없습니다. "
                "사이드바의 **필터 설정** 을 완화해보세요."
            )
            return

        if ranked.empty:
            idx_cache = cache_load_index(index_code, days=rs_period + 10)
            if idx_cache is None or idx_cache.empty or len(idx_cache) < rs_period + 1:
                st.warning(
                    f"**{index_display}** 지수 시세가 캐시에 없거나 부족합니다. "
                    "사이드바에서 이 지수를 선택한 상태로 "
                    "**[FDR에서 내려받기]** 를 눌러 지수 데이터를 받아주세요."
                )
            else:
                st.warning(
                    f"{index_display} {rs_period}일 변동폭이 너무 작아 "
                    "RS 계산이 불가합니다. 기간을 늘려보세요."
                )
            return

        if idx_return is not None and idx_return < 0:
            st.info(
                "⚠️ 기준 지수 수익률이 **음수**입니다. "
                "이때 RS는 '지수보다 덜 떨어졌거나 더 오른 종목'을 의미하며, "
                "양수 장에서의 RS 해석과 반대가 될 수 있습니다."
            )

        selected_ticker = _render_ranking_table_kr(ranked, rs_period)
        if selected_ticker is not None:
            st.session_state[KEY_KR_SELECTED_TICKER] = selected_ticker

    with col_right:
        st.markdown("### 차트 패널")
        selected = st.session_state.get(KEY_KR_SELECTED_TICKER)
        if selected:
            _kr_render_chart(str(selected), lookback_days=120)
        else:
            st.info(
                "좌측 테이블에서 종목을 선택하면 "
                "캔들스틱 + 5일 이평선 + 9일 ATR 차트가 표시됩니다."
            )


def render_crypto_tab() -> None:
    """코인 탭 (Phase 3 예정)."""
    st.info("코인은 Phase 3에서 지원 예정입니다.")
