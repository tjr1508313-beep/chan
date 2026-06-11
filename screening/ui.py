"""스크리닝 앱 UI 렌더링 (Toss-style 통합본).

이 파일을 `screening/ui.py` 에 그대로 덮어쓰세요.
기존 인터페이스(`render_screening_page`) 100% 호환.

기존 기능 + 토스 스타일 신규 요소:
    - 상단 시장 요약 카드 (US/KR 나란히)  ──── Step 1
    - 종목별 즐겨찾기 별표 + 사이드바 토글  ── Step 2
    - 행에 20일 미니 스파크라인 (SVG)        ── Step 3

⚠️ `theme.py` 도 함께 토스 통합본으로 교체해야 색/CSS 가 매칭됩니다.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pandas as pd
import streamlit as st
from lightweight_charts_pro.charts.options.line_options import LineOptions
from lightweight_charts_pro.charts.options.price_format_options import PriceFormatOptions
from lightweight_charts_pro.charts.options.time_scale_options import TimeScaleOptions
from streamlit_lightweight_charts_pro import (
    CandlestickSeries,
    Chart,
    ChartOptions,
    LayoutOptions,
    LineSeries,
    PaneHeightOptions,
)

from .batch import screen_refresh_index, screen_refresh_meta, screen_refresh_prices
from .batch_kr import (
    screen_refresh_index_kr,
    screen_refresh_meta_kr,
    screen_refresh_prices_kr,
)
from .cache import (
    cache_get_all_last_price_dates,
    cache_load_index,
    cache_load_meta,
    cache_load_prices,
    cache_load_universe,
    cache_prune_orphan_prices,
    cache_save_universe,
)
from .cache_sync import get_last_sync_info, sync_from_remote
from .core import (
    calc_weighted_rs,
    calc_wilder_atr,
    screen_apply_filters,
    screen_build_screening_df,
    screen_calc_rs,
    screen_filter_by_index_lag,
    screen_rank_rs,
    screen_rebuild_computed_snapshot,
)
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


# ─── 차트 색상 ─────────────────────────────────────────────────────
_COLOR_UP = COLOR_PROFIT
_COLOR_DOWN = COLOR_LOSS
_COLOR_MA5 = "#ff9500"
_COLOR_MA20 = "#22c55e"
_COLOR_MA60 = "#a855f7"
_COLOR_ATR = "#6366f1"

_INDEX_DISPLAY = {
    "^IXIC": "나스닥",
    "^GSPC": "S&P 500",
    "KS11": "코스피",
    "KQ11": "코스닥",
}


# ─── 데이터 획득 ────────────────────────────────────────────────────

def _fetch_index_tickers_from_source(index_code: str) -> list[str]:
    if index_code == "^IXIC":
        return us_get_nasdaq_tickers()
    if index_code == "^GSPC":
        return us_get_sp500_tickers()
    if index_code == "KS11":
        return kr_get_kospi_tickers()
    if index_code == "KQ11":
        return kr_get_kosdaq_tickers()
    return []


def ui_refresh_index_universe(index_code: str) -> list[str]:
    tickers = _fetch_index_tickers_from_source(index_code)
    if tickers:
        cache_save_universe(index_code, tickers)
    return tickers


@st.cache_data(ttl=3600, show_spinner=False)
def ui_load_index_tickers(index_code: str) -> list[str]:
    cached = cache_load_universe(index_code)
    if cached:
        return cached
    try:
        return ui_refresh_index_universe(index_code)
    except Exception:
        # 콜드 캐시 + 소스 실패(예: KRX 해외 IP 차단) 시 앱 로드가 죽지 않도록 빈 목록 반환.
        return []


@st.cache_data(ttl=300, show_spinner=False)
def ui_load_ranked_df(
    index_code: str,
    rs_period: int,
    top_n: int,
    filter_config: dict,
    tickers_tuple: tuple[str, ...],
) -> tuple[pd.DataFrame, dict]:
    tickers = list(tickers_tuple)
    if not tickers:
        return pd.DataFrame(), {"total": 0, "final": 0}

    df = screen_build_screening_df(tickers, lookback_days=20)
    filtered, stats = screen_apply_filters(df, filter_config)

    passing, lag_excluded = screen_filter_by_index_lag(
        filtered.index.tolist(), index_code, max_lag_days=0
    )
    stats["lag_excluded"] = int(lag_excluded)
    stats["after_lag"] = int(len(passing))

    if not passing:
        return pd.DataFrame(), stats

    ranked = screen_rank_rs(passing, index_code, period=rs_period, top_n=top_n)
    if not ranked.empty:
        meta_cols = filtered[["name_en", "name_kr", "avg_traded_value_20d", "market_cap"]]
        ranked = ranked.merge(meta_cols, left_on="ticker", right_index=True, how="left")
    return ranked, stats


@st.cache_data(ttl=300, show_spinner=False)
def ui_load_chart_df(ticker: str, days: int) -> pd.DataFrame:
    return cache_load_prices(ticker, days=days)


# ─── 공통 헬퍼 ──────────────────────────────────────────────────────

def _index_display_name(index_code: str) -> str:
    return _INDEX_DISPLAY.get(index_code, index_code)


def _sort_tickers_stale_first(tickers: list[str], normalize_upper: bool) -> list[str]:
    last_dates = cache_get_all_last_price_dates()

    def key(t: str):
        lookup = t.upper() if normalize_upper else str(t)
        last = last_dates.get(lookup)
        return (last is not None, last or "")

    return sorted(tickers, key=key)


def _get_index_period_info(index_code: str, rs_period: int) -> dict | None:
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


# ─── ★ Step 3: 스파크라인 ───────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def _load_spark_data(ticker: str, days: int = 22) -> list[float]:
    """스파크라인용 정규화 종가 리스트 (0~1)."""
    df = cache_load_prices(ticker, days=days)
    if df is None or df.empty or "Close" not in df.columns:
        return []
    s = df["Close"].dropna().tail(days).tolist()
    if len(s) < 3:
        return []
    lo, hi = min(s), max(s)
    if hi == lo:
        return [0.5] * len(s)
    return [(v - lo) / (hi - lo) for v in s]


def _spark_svg(values: list[float], up: bool, w: int = 90, h: int = 28) -> str:
    """정규화 0~1 시계열을 inline SVG polyline 으로."""
    if not values:
        return (
            f"<svg width='{w}' height='{h}' viewBox='0 0 {w} {h}'>"
            f"<line x1='4' y1='{h//2}' x2='{w-4}' y2='{h//2}' "
            f"stroke='#d1d6db' stroke-width='1' stroke-dasharray='3 3'/></svg>"
        )
    color = COLOR_PROFIT if up else COLOR_LOSS
    n = len(values)
    pts = " ".join(
        f"{(i / (n - 1)) * (w - 4) + 2:.1f},{h - v * (h - 4) - 2:.1f}"
        for i, v in enumerate(values)
    )
    last_x = w - 2
    last_y = h - values[-1] * (h - 4) - 2
    return (
        f"<svg width='{w}' height='{h}' viewBox='0 0 {w} {h}' style='display:block;'>"
        f"<polyline points='{pts}' fill='none' stroke='{color}' "
        f"stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'/>"
        f"<circle cx='{last_x:.1f}' cy='{last_y:.1f}' r='2' fill='{color}'/>"
        f"</svg>"
    )


# ─── ★ Step 2: 즐겨찾기 ─────────────────────────────────────────────

def _ensure_favs(spec: dict) -> str:
    """session_state 에 favorites set 보장하고 키 반환."""
    key = _key(spec, "favs")
    if key not in st.session_state:
        st.session_state[key] = set()
    return key


def _make_fav_callback(spec: dict, ticker: str):
    """별표 클릭 핸들러 — favorites set 토글."""
    def _cb() -> None:
        key = _ensure_favs(spec)
        favs = st.session_state[key]
        if ticker in favs:
            favs.discard(ticker)
        else:
            favs.add(ticker)
    return _cb


def _apply_fav_filter(spec: dict, ranked: pd.DataFrame) -> pd.DataFrame:
    """`only_fav` 토글이 켜져 있으면 favorites 만 남기고 rank 재계산."""
    if not st.session_state.get(_key(spec, "only_fav"), False):
        return ranked
    favs = st.session_state.get(_key(spec, "favs"), set())
    if not favs or ranked.empty:
        return ranked.iloc[0:0]
    filtered = ranked[ranked["ticker"].isin(favs)].copy().reset_index(drop=True)
    filtered["rank"] = range(1, len(filtered) + 1)
    return filtered


def _render_fav_toggle_sidebar(spec: dict) -> None:
    """사이드바 — '즐겨찾기만 보기' 토글 + 현재 즐겨찾기 개수."""
    _ensure_favs(spec)
    favs_count = len(st.session_state[_key(spec, "favs")])
    st.toggle(
        f"★ 즐겨찾기만 보기 ({favs_count})",
        key=_key(spec, "only_fav"),
        help="별표한 종목만 랭킹에 표시합니다.",
    )


# ─── ★ Step 1: 시장요약 카드 ────────────────────────────────────────

def _stat_block(label: str, value, color: str, suffix: str = "") -> str:
    """카드 내부 작은 통계 블록 HTML."""
    return (
        f"<div style='background:#f9fafb; border-radius:12px; padding:10px 12px;'>"
        f"<div style='color:#8b95a1; font-size:11px; font-weight:500;'>{label}</div>"
        f"<div style='font-family:\"JetBrains Mono\",ui-monospace,monospace; "
        f"font-variant-numeric:tabular-nums; font-size:17px; font-weight:700; "
        f"color:{color}; margin-top:2px;'>"
        f"{value}"
        f"<span style='color:#8b95a1; font-size:12px; font-weight:500; margin-left:3px;'>"
        f"{suffix}</span>"
        f"</div></div>"
    )


def _render_market_card(spec: dict, settings: tuple) -> None:
    """자산군 시장요약 카드 — 지수 종가 + N일 수익률 + 상위 종목 통계."""
    index_code, rs_period, top_n, filter_config = settings

    info = _get_index_period_info(index_code, rs_period)
    display = _index_display_name(index_code)

    if info is None:
        st.markdown(
            f"<div style='background:#fff; border:1px solid #f1f3f5; border-radius:20px; "
            f"padding:22px 24px; min-height:180px; display:flex; align-items:center; "
            f"justify-content:center; color:#8b95a1; font-size:13px;'>"
            f"{display} 지수 캐시가 부족합니다. 사이드바에서 새로고침 해주세요."
            f"</div>",
            unsafe_allow_html=True,
        )
        return

    tickers = ui_load_index_tickers(index_code)
    ranked, _stats = ui_load_ranked_df(
        index_code=index_code,
        rs_period=rs_period,
        top_n=top_n,
        filter_config=filter_config,
        tickers_tuple=tuple(tickers),
    )

    if not ranked.empty and "return_n" in ranked.columns:
        adv = int((ranked["return_n"] > 0).sum())
        dec = int((ranked["return_n"] < 0).sum())
        avg_rs = float(ranked["rs"].mean())
    else:
        adv = dec = 0
        avg_rs = 0.0

    flag = "🇺🇸" if spec["code"] == "us" else "🇰🇷"
    up = info["return_pct"] >= 0
    color = COLOR_PROFIT if up else COLOR_LOSS
    sign = "+" if up else ""

    st.markdown(
        f"""
        <div style='background:#fff; border:1px solid #f1f3f5; border-radius:20px;
                    padding:22px 24px; box-shadow:0 1px 2px rgba(16,24,40,.04),
                                                  0 2px 8px rgba(16,24,40,.04);'>
          <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;'>
            <div style='display:flex; align-items:center; gap:8px;'>
              <span style='background:#f1f3f5; color:#4e5968; padding:4px 10px;
                           border-radius:999px; font-size:12px; font-weight:600;'>
                {flag} {spec['label']}
              </span>
              <span style='font-size:17px; font-weight:700; color:#191f28;'>{display}</span>
            </div>
            <span style='color:#8b95a1; font-size:12px;'>{info['end_date']}</span>
          </div>
          <div style='display:flex; align-items:flex-end; gap:14px; margin-bottom:18px;'>
            <div style='font-family:"JetBrains Mono",ui-monospace,monospace;
                        font-variant-numeric:tabular-nums;
                        font-size:30px; font-weight:800; line-height:1.1; color:#191f28;'>
              {info['end_close']:,.2f}
            </div>
            <div style='font-family:"JetBrains Mono",ui-monospace,monospace;
                        font-variant-numeric:tabular-nums;
                        color:{color}; font-size:16px; font-weight:700; padding-bottom:3px;'>
              {sign}{info['return_pct']:.2f}%
              <span style='color:#8b95a1; font-size:12px; font-weight:500; margin-left:4px;'>
                · 최근 {rs_period}일
              </span>
            </div>
          </div>
          <div style='display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px;'>
            {_stat_block(f'Top {top_n} 상승', adv, COLOR_PROFIT, '개')}
            {_stat_block(f'Top {top_n} 하락', dec, COLOR_LOSS, '개')}
            {_stat_block('평균 RS', f'{avg_rs:.2f}', '#191f28')}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )



# ─── 자산군 spec dict ───────────────────────────────────────────────

_US_SPEC: dict[str, Any] = {
    "code": "us",
    "label": "미국주식",
    "indices": {"나스닥": "^IXIC", "S&P 500": "^GSPC"},
    "key_prefix": "scr",
    "normalize_upper": True,

    "refresh_data_label": "yfinance",
    "refresh_btn": "yfinance에서 내려받기",
    "refresh_btn_help": (
        "지수 + 전체 구성종목의 시세/메타를 yfinance 에서 병렬로 내려받아 "
        "로컬 SQLite 에 저장. 캐시가 오래됐거나 없는 종목부터 우선 처리. "
        "나스닥 전체(3800+) 첫 다운로드 ≈ 15~25분, 이후 증분은 수 분."
    ),
    "refresh_index_fn": screen_refresh_index,
    "refresh_prices_fn": screen_refresh_prices,
    "refresh_meta_fn": screen_refresh_meta,
    "prices_max_workers": 4,
    "meta_max_workers": 4,
    "force_help": (
        "이전 캐시를 덮어쓰고 yfinance 에서 다시 받음. 분할/spin-off 등 "
        "corporate action 이후 historical 가격이 retroactively 재조정된 "
        "경우 이 옵션으로 정합성 복구."
    ),

    "currency": "$",
    "price_col_format": "$%.2f",
    "price_chart_fmt": lambda v: f"${v:,.2f}",
    "price_hover_fmt": "$%{y:,.2f}",
    "atr_fmt": lambda v: f"${v:,.2f}",
    "chart_price_precision": 2,
    "chart_price_min_move": 0.01,

    "dv_label": "거래대금(M$)",
    "dv_divisor": 1_000_000.0,
    "dv_col_format": "%.1f",
    "dv_metric_fmt": lambda v: f"${v:,.1f}M",

    "show_market_cap_column": False,

    "min_price_label": "최소 주가 ($)",
    "min_price_default": 10.0,
    "min_price_max": 10_000.0,
    "min_price_step": 1.0,
    "min_dv_label": "최소 평균 거래대금 (백만 $)",
    "min_dv_default": 20.0,
    "min_dv_max": 10_000.0,
    "min_dv_step": 5.0,
    "min_dv_help": "20일 평균 일 거래대금. 20M ≈ 300억 원.",
    "min_dv_to_raw": lambda v: v * 1_000_000.0,
    "min_dv_summary_fmt": lambda raw: f"${raw/1_000_000:.0f}M",
    "min_price_summary_fmt": lambda v: f"≥ ${v:.0f}",

    "show_market_cap_filter": False,
    "show_china_filter": True,
    "show_risk_filter": False,

    "extra_caption": None,
    "ticker_col_label": "티커",
}

_KR_SPEC: dict[str, Any] = {
    "code": "kr",
    "label": "한국주식",
    "indices": {"코스피": "KS11", "코스닥": "KQ11"},
    "key_prefix": "scr_kr",
    "normalize_upper": False,

    "refresh_data_label": "FDR",
    "refresh_btn": "FDR에서 내려받기",
    "refresh_btn_help": (
        "지수 + 전체 구성종목의 시세/메타를 FinanceDataReader 에서 병렬로 "
        "내려받아 로컬 SQLite 에 저장. 캐시가 오래됐거나 없는 종목부터 우선 처리. "
        "코스피 전체(950) 첫 다운로드 ≈ 2~3분, 코스닥 전체(1800) ≈ 4~6분."
    ),
    "refresh_index_fn": screen_refresh_index_kr,
    "refresh_prices_fn": screen_refresh_prices_kr,
    "refresh_meta_fn": screen_refresh_meta_kr,
    "prices_max_workers": 8,
    "meta_max_workers": None,
    "force_help": (
        "이전 캐시를 덮어쓰고 FDR 에서 다시 받음. 분할/액면분할 등 이후 "
        "historical 가격이 retroactively 재조정된 경우 정합성 복구용."
    ),

    "currency": "₩",
    "price_col_format": "₩%,d",
    "price_chart_fmt": lambda v: f"₩{v:,.0f}",
    "price_hover_fmt": "₩%{y:,.0f}",
    "atr_fmt": lambda v: f"₩{v:,.0f}",
    "chart_price_precision": 0,
    "chart_price_min_move": 1.0,

    "dv_label": "거래대금(억)",
    "dv_divisor": 100_000_000.0,
    "dv_col_format": "%,.0f",
    "dv_metric_fmt": lambda v: f"{v:,.0f}억",

    "show_market_cap_column": True,

    "min_price_label": "최소 주가 (원)",
    "min_price_default": 1_000,
    "min_price_max": 10_000_000,
    "min_price_step": 100,
    "min_dv_label": "최소 평균 거래대금 (억 원)",
    "min_dv_default": 300,
    "min_dv_max": 100_000,
    "min_dv_step": 50,
    "min_dv_help": "20일 평균 일 거래대금. 한국주식 기본 기준 = 300억 원.",
    "min_dv_to_raw": lambda v: v * 100_000_000.0,
    "min_dv_summary_fmt": lambda raw: f"≥ {raw/100_000_000:,.0f}억",
    "min_price_summary_fmt": lambda v: f"≥ {v:,.0f}원",

    "show_market_cap_filter": True,
    "min_marketcap_label": "최소 시가총액 (억 원)",
    "min_marketcap_default": 3_000,
    "min_marketcap_max": 10_000_000,
    "min_marketcap_step": 500,
    "min_marketcap_help": "시가총액이 너무 작은 종목 배제. 사용자 결정 기본 3,000억.",
    "min_marketcap_to_raw": lambda v: v * 100_000_000.0,
    "min_marketcap_summary_fmt": lambda raw: f"시총 ≥ {raw/100_000_000:,.0f}억",

    "show_china_filter": False,
    "show_risk_filter": True,

    "extra_caption": "✓ 모집단 단계에서 우선주/리츠/ETF/스팩/외국기업은 자동 제외됨",
    "ticker_col_label": "코드",
}


def _key(spec: dict, suffix: str) -> str:
    return f"{spec['key_prefix']}_{suffix}"


# ─── 사이드바 ──────────────────────────────────────────────────────

def _render_index_status_badge(index_code: str) -> None:
    idx_cache = cache_load_index(index_code, days=5)
    cached = idx_cache is not None and not idx_cache.empty
    color = "#1a9cff" if cached else "#ff9500"
    text = "데이터 준비됨" if cached else "데이터 없음"
    st.markdown(
        f"<div style='font-size:0.78rem; color:{COLOR_MUTED}; margin-top:-4px;'>"
        f"지수 상태: <span style='color:{color}; font-weight:600;'>{text}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _render_sidebar(spec: dict) -> tuple[str, int, int, dict]:
    """자산군 사이드바 → (index_code, rs_period, top_n, filter_config)."""
    with st.sidebar:
        st.markdown(f"##### {spec['label']} 설정")

        index_options = spec["indices"]
        selected_label = st.selectbox(
            "지수 선택",
            options=list(index_options.keys()),
            index=0,
            key=_key(spec, "selected_index"),
            help=f"RS 계산의 기준 지수 ({spec['refresh_data_label']}).",
        )
        index_code = index_options[selected_label]

        rs_period = st.slider(
            "RS 계산 기간 (일)",
            min_value=5, max_value=60, value=20, step=1,
            key=_key(spec, "rs_period"),
            help="RS = (종목 N일 수익률) / (지수 N일 수익률)",
        )
        top_n = st.slider(
            "표시 개수 (Top N)",
            min_value=10, max_value=50, value=20, step=5,
            key=_key(spec, "top_n"),
            help="랭킹 테이블에 표시할 상위 종목 수.",
        )
        _render_index_status_badge(index_code)

        _render_refresh_section(spec, index_code)

        # ★ Step 2: 즐겨찾기 토글
        st.divider()
        _render_fav_toggle_sidebar(spec)

        st.divider()
        with st.expander("필터 설정", expanded=False):
            min_price = st.number_input(
                spec["min_price_label"],
                min_value=type(spec["min_price_default"])(0),
                max_value=spec["min_price_max"],
                value=spec["min_price_default"],
                step=spec["min_price_step"],
                key=_key(spec, "filter_min_price"),
            )
            min_dv = st.number_input(
                spec["min_dv_label"],
                min_value=type(spec["min_dv_default"])(0),
                max_value=spec["min_dv_max"],
                value=spec["min_dv_default"],
                step=spec["min_dv_step"],
                key=_key(spec, "filter_min_dv"),
                help=spec["min_dv_help"],
            )
            min_mc_raw = 0.0
            if spec["show_market_cap_filter"]:
                min_mc_input = st.number_input(
                    spec["min_marketcap_label"],
                    min_value=0,
                    max_value=spec["min_marketcap_max"],
                    value=spec["min_marketcap_default"],
                    step=spec["min_marketcap_step"],
                    key=_key(spec, "filter_min_marketcap"),
                    help=spec["min_marketcap_help"],
                )
                min_mc_raw = spec["min_marketcap_to_raw"](min_mc_input)
            max_range_pct = st.slider(
                "최근 20일 최대 일일 변동폭 한도 (%)",
                min_value=10, max_value=100, value=50, step=5,
                key=_key(spec, "filter_max_range_pct"),
                help="이 값 이상 변동한 날이 있는 종목은 제외.",
            )
            exclude_atr_drop = st.checkbox(
                "최근 1~2일 급락 종목 제외",
                value=True,
                key=_key(spec, "filter_exclude_atr_drop"),
                help=(
                    "당일(D-0) 또는 전일(D-1) 종가 하락폭이 "
                    "9일 ATR × 임계값 이상이면 제외. "
                    "ATR 은 lookahead 방지를 위해 직전일까지의 값 사용."
                ),
            )
            atr_drop_mult = st.slider(
                "급락 한도 (9일 ATR × 배수)",
                min_value=1.0, max_value=5.0, value=2.5, step=0.1,
                key=_key(spec, "filter_atr_drop_mult"),
                disabled=not exclude_atr_drop,
                help="값이 작을수록 더 많이 거름. 기본 2.5배.",
            )
            exclude_china = False
            if spec["show_china_filter"]:
                exclude_china = st.checkbox(
                    "중국기업 제외", value=True,
                    key=_key(spec, "filter_exclude_china"),
                )
            if spec.get("show_risk_filter", True):
                exclude_risk = st.checkbox(
                    "관리/위험종목 제외", value=True,
                    key=_key(spec, "filter_exclude_risk"),
                    help=(
                        "KRX 공시 기반 관리종목/투자주의/거래정지 제외. "
                        "위험종목 데이터를 사이드바 새로고침에서 갱신해야 효과가 적용됩니다."
                    ),
                )
            else:
                exclude_risk = False
            if spec["extra_caption"]:
                st.caption(spec["extra_caption"])

        filter_config = {
            "min_price": float(min_price),
            "min_traded_value": spec["min_dv_to_raw"](min_dv),
            "min_market_cap": float(min_mc_raw),
            "max_daily_range_pct": float(max_range_pct) / 100.0,
            "max_atr_drop_multiple": float(atr_drop_mult) if exclude_atr_drop else 0.0,
            "exclude_china": bool(exclude_china),
            "exclude_risk": bool(exclude_risk),
        }

    return index_code, int(rs_period), int(top_n), filter_config


# ─── 새로고침 (백그라운드 스레드) ─────────────────────────────────

def _refresh_worker(
    spec: dict, index_code: str, target: list[str], force: bool, job: dict
) -> None:
    try:
        job["phase"] = "지수 시세"
        idx_result = spec["refresh_index_fn"](index_code, days=300, force=force)
        job["messages"].append(f"지수: {idx_result}")

        job["phase"] = "종목 시세"

        def _px_cb(done: int, total: int) -> None:
            job["px_done"] = done
            job["px_total"] = total

        px_result = spec["refresh_prices_fn"](
            target,
            days=300,
            force=force,
            max_workers=spec["prices_max_workers"],
            progress_cb=_px_cb,
        )
        px_parts = [
            f"updated={px_result['updated']}",
            f"skipped={px_result['skipped']}",
            f"failed={len(px_result['failed'])}",
        ]
        fr = px_result.get("force_refetched", 0)
        if fr:
            px_parts.append(f"분할재요청={fr}")
        job["messages"].append("시세: " + ", ".join(px_parts))

        job["phase"] = "메타데이터"
        meta_workers = spec.get("meta_max_workers")
        if meta_workers:
            def _meta_cb(done: int, total: int) -> None:
                job["meta_done"] = done
                job["meta_total"] = total

            meta_result = spec["refresh_meta_fn"](
                target,
                ttl_days=7,
                force=force,
                max_workers=meta_workers,
                progress_cb=_meta_cb,
            )
        else:
            meta_result = spec["refresh_meta_fn"](target, ttl_days=7, force=force)
            job["meta_done"] = len(target)
        job["messages"].append(
            f"메타: updated={meta_result['updated']}, "
            f"skipped={meta_result['skipped']}, "
            f"failed={len(meta_result['failed'])}"
        )

        pruned = cache_prune_orphan_prices(vacuum=False)
        if pruned:
            job["messages"].append(f"정리: 죽은 티커 시세 {pruned:,}행 삭제")

        job["phase"] = "화면 데이터 미리 계산"
        computed = screen_rebuild_computed_snapshot(target)
        job["messages"].append(
            f"미리 계산: 종목={computed['metrics']}, 수익률={computed['returns']}"
        )

        job["phase"] = "완료"
    except Exception as e:
        job["error"] = str(e)
        job["phase"] = "실패"
    finally:
        job["running"] = False
        job["finished_at"] = time.time()


def _start_refresh(spec: dict, index_code: str, force: bool) -> None:
    job_key = _key(spec, "refresh_job")
    existing = st.session_state.get(job_key)
    if existing and existing.get("running"):
        return

    # 구성종목 소스 갱신은 메인 스레드에서 동기 실행된다. 해외 IP(예: Streamlit
    # Cloud)에서 KRX(data.krx.co.kr)가 차단되면 fdr.StockListing 이 ValueError 를
    # 던지는데, 여기서 잡지 않으면 render 전체가 죽는다. 캐시 유니버스로 폴백해
    # 시세/메타 갱신은 계속 진행한다 (한국 시세는 Naver 소스라 해외 IP 에서도 동작).
    universe_error: str | None = None
    try:
        tickers = ui_refresh_index_universe(index_code)
    except Exception as e:
        tickers = cache_load_universe(index_code)
        universe_error = str(e)

    if not tickers:
        st.session_state[job_key] = {
            "running": False,
            "phase": "실패",
            "error": (
                f"구성종목 리스트를 가져오지 못했습니다: {universe_error}"
                if universe_error
                else "구성종목 리스트를 가져오지 못했습니다."
            ),
            "messages": [],
            "px_done": 0, "px_total": 0,
            "meta_done": 0, "meta_total": 0,
            "index_code": index_code, "force": force,
            "started_at": time.time(), "finished_at": time.time(),
            "cache_cleared": True,
        }
        return

    target = _sort_tickers_stale_first(
        tickers, normalize_upper=spec["normalize_upper"]
    )
    messages: list[str] = []
    if universe_error:
        messages.append(
            f"⚠️ 구성종목 갱신 실패 → 캐시 목록 사용 ({len(target)}종목). "
            "시세/메타만 갱신합니다."
        )
    job: dict[str, Any] = {
        "running": True,
        "phase": "준비 중",
        "error": None,
        "messages": messages,
        "px_done": 0, "px_total": len(target),
        "meta_done": 0, "meta_total": len(target),
        "index_code": index_code, "force": force,
        "started_at": time.time(), "finished_at": None,
        "cache_cleared": False,
    }
    st.session_state[job_key] = job
    thread = threading.Thread(
        target=_refresh_worker,
        args=(spec, index_code, target, force, job),
        daemon=True,
    )
    thread.start()


def _render_refresh_progress(spec: dict, job: dict) -> None:
    elapsed = int(time.time() - job.get("started_at", time.time()))
    st.caption(f"⏳ {job['phase']} 진행 중 … ({elapsed}초 경과)")

    px_total = job.get("px_total") or 0
    if px_total:
        px_done = job.get("px_done", 0)
        st.progress(min(px_done / px_total, 1.0), text=f"시세 {px_done} / {px_total}")
    if job["phase"] == "메타데이터":
        meta_total = job.get("meta_total") or 0
        if meta_total:
            meta_done = job.get("meta_done", 0)
            st.progress(
                min(meta_done / meta_total, 1.0),
                text=f"메타 {meta_done} / {meta_total}",
            )


def _render_refresh_result(spec: dict, job: dict) -> None:
    if not job.get("cache_cleared"):
        ui_load_ranked_df.clear()
        ui_load_chart_df.clear()
        job["cache_cleared"] = True

    if job.get("error"):
        st.error(f"새로고침 실패: {job['error']}")
        return
    st.success("새로고침 완료")
    for msg in job.get("messages", []):
        st.caption(msg)


@st.fragment(run_every=2)
def _refresh_progress_fragment(spec: dict) -> None:
    job = st.session_state.get(_key(spec, "refresh_job"))
    if not job:
        return
    if job.get("running"):
        _render_refresh_progress(spec, job)
        return
    if not job.get("ui_finalized"):
        job["ui_finalized"] = True
        st.rerun(scope="app")


def _render_refresh_section(spec: dict, index_code: str) -> None:
    st.divider()
    st.markdown("##### 데이터 새로고침")

    job = st.session_state.get(_key(spec, "refresh_job"))
    running = bool(job and job.get("running"))

    force_refresh = st.checkbox(
        "캐시 무시하고 전부 새로 받기 (force)",
        value=False,
        key=_key(spec, "force_refresh"),
        help=spec["force_help"],
        disabled=running,
    )
    if st.button(
        spec["refresh_btn"],
        width="stretch",
        help=spec["refresh_btn_help"],
        key=_key(spec, "refresh_btn"),
        disabled=running,
    ):
        _start_refresh(spec, index_code, force=bool(force_refresh))
        st.rerun()

    if running:
        _refresh_progress_fragment(spec)
    elif job:
        _render_refresh_result(spec, job)


# ─── 헤더/배지/필터 요약 ───────────────────────────────────────────

def _render_rs_header(
    index_code: str, index_display: str, rs_period: int, top_n: int
) -> None:
    info = _get_index_period_info(index_code, rs_period)
    cols = st.columns([2, 1.4])
    with cols[0]:
        st.markdown(f"### RS Top {top_n}")
        st.caption(f"RS = (종목 {rs_period}일 수익률) / (지수 {rs_period}일 수익률)")
    with cols[1]:
        if info is None:
            return
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
            f"</div></div>",
            unsafe_allow_html=True,
        )


def _render_pipeline_badge(stats: dict, ranked_len: int) -> None:
    total = stats.get("total", 0)
    if total == 0:
        return
    parts = [
        f"전체 {total}",
        f"주가 {stats.get('after_price', 0)}",
        f"거래대금 {stats.get('after_volume', 0)}",
    ]
    after_mc = stats.get("after_market_cap")
    if after_mc is not None and after_mc != stats.get("after_volume"):
        parts.append(f"시총 {after_mc}")
    parts.extend([
        f"관리 {stats.get('after_risk', 0)}",
        f"중국 {stats.get('after_china', 0)}",
        f"변동성 {stats.get('after_volatility', 0)}",
    ])
    after_atr_drop = stats.get("after_atr_drop")
    if after_atr_drop is not None and after_atr_drop != stats.get("after_volatility"):
        parts.append(f"급락 {after_atr_drop}")
    lag_excluded = stats.get("lag_excluded", 0)
    if lag_excluded:
        parts.append(f"지연 -{lag_excluded}")
    parts.append(f"상위 {ranked_len}")
    st.markdown(
        f"<div style='font-size:0.92rem; color:{COLOR_TEXT}; "
        f"margin-top:4px; margin-bottom:8px;'>"
        + " → ".join(parts)
        + "</div>",
        unsafe_allow_html=True,
    )


def _render_filter_summary(spec: dict, cfg: dict) -> None:
    badges = [
        f"주가 {spec['min_price_summary_fmt'](cfg['min_price'])}",
        f"거래대금 {spec['min_dv_summary_fmt'](cfg['min_traded_value'])}",
    ]
    min_mc = cfg.get("min_market_cap", 0)
    if min_mc > 0 and "min_marketcap_summary_fmt" in spec:
        badges.append(spec["min_marketcap_summary_fmt"](min_mc))
    badges.append(f"변동폭 < {cfg['max_daily_range_pct']*100:.0f}%")
    max_drop = cfg.get("max_atr_drop_multiple", 0) or 0
    if max_drop > 0:
        badges.append(f"급락 < ATR×{max_drop:.1f}")
    if spec["show_china_filter"] and cfg.get("exclude_china"):
        badges.append("중국 제외")
    if cfg.get("exclude_risk"):
        suffix = "*" if spec["code"] == "kr" else ""
        badges.append(f"관리 제외{suffix}")
    st.markdown(
        f"<div style='font-size:0.92rem; color:{COLOR_TEXT}; "
        f"margin-top:4px; margin-bottom:2px;'>"
        f"<span style='color:{COLOR_MUTED};'>필터:</span> "
        + " · ".join(badges)
        + "</div>",
        unsafe_allow_html=True,
    )


# ─── 랭킹 테이블 ────────────────────────────────────────────────────

def _make_pick_callback(spec: dict, ticker: str):
    target_key = _key(spec, "selected_ticker")

    def _cb() -> None:
        st.session_state[target_key] = ticker

    return _cb


def _first_valid_name(*candidates: object) -> str:
    for c in candidates:
        if c is None:
            continue
        try:
            if pd.isna(c):
                continue
        except (TypeError, ValueError):
            pass
        s = str(c).strip()
        if s:
            return s
    return ""


def _fmt_cell(value, fmt: str, na: str = "—") -> str:
    if value is None:
        return na
    try:
        if pd.isna(value):
            return na
    except (TypeError, ValueError):
        pass
    if fmt.startswith("%"):
        spec_ = fmt[1:]
        suffix = ""
        if spec_.endswith("%%"):
            spec_ = spec_[:-2]
            suffix = "%"
        try:
            return format(value, spec_) + suffix
        except (TypeError, ValueError):
            pass
    try:
        return format(value, fmt)
    except (TypeError, ValueError):
        return str(value)


def _render_ticker_search_result(
    spec: dict, raw_input: str, rs_period: int, index_code: str
) -> None:
    """검색된 티커의 정보 카드를 랭킹 테이블 위에 표시."""
    ticker = raw_input.strip().upper() if spec.get("normalize_upper", True) else raw_input.strip()
    if not ticker:
        return

    days_needed = max(rs_period + 10, 263)
    prices = cache_load_prices(ticker, days=days_needed)
    if prices is None or prices.empty:
        st.warning(
            f"**{ticker}** 캐시 데이터가 없습니다. "
            "새로고침 후 다시 시도하거나 티커를 확인해주세요.",
            icon="🔍",
        )
        return

    index_prices = cache_load_index(index_code, days=days_needed)
    meta = cache_load_meta(ticker) or {}

    close = prices["Close"]
    last_price = float(close.iloc[-1])

    # RS (지수 대비)
    rs_series = screen_calc_rs(prices, index_prices, period=rs_period)
    rs_val = float(rs_series.iloc[0]) if not rs_series.empty else float("nan")

    # RS 가중
    rs_w = calc_weighted_rs(close)

    # N일 수익률
    if len(close) > rs_period:
        ret_n = float(close.iloc[-1]) / float(close.iloc[-rs_period - 1]) - 1
    else:
        ret_n = float("nan")

    # 5일 수익률
    if len(close) > 5:
        ret_5 = float(close.iloc[-1]) / float(close.iloc[-6]) - 1
    else:
        ret_5 = float("nan")

    # 20일 평균 거래대금
    tv = prices.get("traded_value") if "traded_value" in prices.columns else None
    avg_tv = float(tv.tail(20).mean()) if tv is not None and tv.dropna().shape[0] > 0 else float("nan")

    name = _first_valid_name(meta.get("name_kr"), meta.get("name_en"), ticker)
    exchange = meta.get("exchange") or ""
    market_cap = meta.get("market_cap")
    is_risk = bool(meta.get("is_risk", False))
    caution_flags = meta.get("caution_flags") or ""

    up = last_price >= (float(close.iloc[-2]) if len(close) > 1 else last_price)
    price_color = COLOR_PROFIT if up else COLOR_LOSS

    def _cfmt(v, fmt, na="—"):
        if v is None or (isinstance(v, float) and (v != v)):
            return na
        try:
            return format(v, fmt)
        except Exception:
            return na

    price_str = spec["price_chart_fmt"](last_price)
    rs_str = _cfmt(rs_val, ".3f") if not (isinstance(rs_val, float) and rs_val != rs_val) else "—"
    rsw_str = _cfmt(rs_w, ".3f") if not (isinstance(rs_w, float) and rs_w != rs_w) else "—"
    ret_str = (f"{ret_n*100:+.2f}%" if not (isinstance(ret_n, float) and ret_n != ret_n) else "—")
    ret5_str = (f"{ret_5*100:+.2f}%" if not (isinstance(ret_5, float) and ret_5 != ret_5) else "—")
    ret_color = COLOR_PROFIT if not (isinstance(ret_n, float) and ret_n != ret_n) and ret_n >= 0 else COLOR_LOSS
    ret5_color = COLOR_PROFIT if not (isinstance(ret_5, float) and ret_5 != ret_5) and ret_5 >= 0 else COLOR_LOSS

    if not (isinstance(avg_tv, float) and avg_tv != avg_tv):
        dv_str = spec["dv_metric_fmt"](avg_tv / spec["dv_divisor"])
    else:
        dv_str = "—"

    if market_cap and not (isinstance(market_cap, float) and market_cap != market_cap):
        if spec.get("show_market_cap_column"):
            mc_str = f"{market_cap/1e8:,.0f}억"
        else:
            mc_str = f"${market_cap/1e9:.1f}B"
    else:
        mc_str = "—"

    risk_badge = " 🔴위험" if is_risk else ""
    caution_badge = ""
    if caution_flags:
        flag_map = {"경고": "🟠경고", "주의": "🟡주의", "과열": "🔥과열"}
        parts = [flag_map.get(f.strip(), f.strip()) for f in caution_flags.split(",") if f.strip()]
        if parts:
            caution_badge = " " + " ".join(parts)

    index_display = _index_display_name(index_code)

    st.markdown(
        f"""
<div style="
  background:{COLOR_CARD};
  border:1.5px solid #3b82f6;
  border-radius:12px;
  padding:16px 20px 14px;
  margin-bottom:10px;
">
  <div style="display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; margin-bottom:10px;">
    <span style="font-size:1.15rem; font-weight:700; color:{COLOR_TEXT};">{ticker}</span>
    <span style="font-size:0.95rem; color:{COLOR_MUTED};">{name}</span>
    {f'<span style="font-size:0.78rem; color:{COLOR_MUTED}; background:#f1f5f9; border-radius:4px; padding:1px 6px;">{exchange}</span>' if exchange else ""}
    {f'<span style="font-size:0.78rem; color:#ef4444;">{risk_badge.strip()}</span>' if risk_badge else ""}
    {f'<span style="font-size:0.78rem;">{caution_badge.strip()}</span>' if caution_badge else ""}
  </div>
  <div style="display:flex; flex-wrap:wrap; gap:18px; align-items:center;">
    <div>
      <div style="font-size:0.72rem; color:{COLOR_MUTED}; margin-bottom:2px;">현재가</div>
      <div style="font-size:1.1rem; font-weight:700; color:{price_color};">{price_str}</div>
    </div>
    <div>
      <div style="font-size:0.72rem; color:{COLOR_MUTED}; margin-bottom:2px;">RS ({rs_period}일, {index_display})</div>
      <div style="font-size:1.05rem; font-weight:600; color:{COLOR_TEXT};">{rs_str}</div>
    </div>
    <div>
      <div style="font-size:0.72rem; color:{COLOR_MUTED}; margin-bottom:2px;">RS 가중</div>
      <div style="font-size:1.05rem; font-weight:600; color:{COLOR_TEXT};">{rsw_str}</div>
    </div>
    <div>
      <div style="font-size:0.72rem; color:{COLOR_MUTED}; margin-bottom:2px;">{rs_period}일 수익률</div>
      <div style="font-size:1.05rem; font-weight:600; color:{ret_color};">{ret_str}</div>
    </div>
    <div>
      <div style="font-size:0.72rem; color:{COLOR_MUTED}; margin-bottom:2px;">5일 수익률</div>
      <div style="font-size:1.05rem; font-weight:600; color:{ret5_color};">{ret5_str}</div>
    </div>
    <div>
      <div style="font-size:0.72rem; color:{COLOR_MUTED}; margin-bottom:2px;">거래대금(20D)</div>
      <div style="font-size:1.0rem; font-weight:500; color:{COLOR_TEXT};">{dv_str}</div>
    </div>
    <div>
      <div style="font-size:0.72rem; color:{COLOR_MUTED}; margin-bottom:2px;">시가총액</div>
      <div style="font-size:1.0rem; font-weight:500; color:{COLOR_TEXT};">{mc_str}</div>
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # 카드 바로 아래 컴팩트 차트
    _render_chart(spec, ticker, lookback_days=90, height=360)

    # col_right 차트도 같은 티커로 동기화
    st.session_state[_key(spec, "selected_ticker")] = ticker


def _render_ranking_table(
    spec: dict, ranked: pd.DataFrame, rs_period: int, index_code: str = ""
) -> str | None:
    """랭킹 테이블 — 별표 컬럼 + 스파크라인 + 행 클릭으로 차트 픽."""
    if ranked.empty:
        return None

    has_weighted = "rs_weighted" in ranked.columns and not ranked["rs_weighted"].isna().all()
    sort_options = ["RS", "RS가중"] if has_weighted else ["RS"]

    pill_col, search_col = st.columns([2.2, 1.5], gap="small")
    with pill_col:
        sort_choice = st.pills(
            "정렬 기준",
            sort_options,
            default="RS",
            label_visibility="collapsed",
            key=_key(spec, "sort_pills"),
        )
    with search_col:
        placeholder = "티커 검색 (AAPL, 005930…)"
        search_input = st.text_input(
            "종목 검색",
            placeholder=placeholder,
            label_visibility="collapsed",
            key=_key(spec, "search_ticker"),
        )

    sort_col = "rs_weighted" if sort_choice == "RS가중" else "rs"

    # 검색 결과 카드 (순위 테이블 위)
    if search_input and search_input.strip():
        _render_ticker_search_result(spec, search_input, rs_period, index_code)

    ranked = (
        ranked
        .sort_values(sort_col, ascending=False, na_position="last", kind="mergesort")
        .reset_index(drop=True)
        .copy()
    )
    ranked["rank"] = range(1, len(ranked) + 1)

    # ★ Step 2: 즐겨찾기 필터
    ranked = _apply_fav_filter(spec, ranked)
    if ranked.empty:
        st.info(
            "★ 즐겨찾기한 종목이 아직 없어요. "
            "랭킹에서 ☆ 을 눌러 추가해보세요."
        )
        return st.session_state.get(_key(spec, "selected_ticker"))

    favs_set = st.session_state.get(_key(spec, "favs"), set())

    # 컬럼 — ★(0), 순위, 코드, 종목명, 현재가, 추이(5), RS, RS가중, 수익률, [시총], 거래대금
    columns: list[tuple[str, float]] = [
        ("★", 0.35),
        ("순위", 0.45),
        (spec["ticker_col_label"], 0.75),
        ("종목명", 2.2),
        ("현재가", 1.1),
        ("추이", 0.9),
        ("RS", 0.7),
        ("RS가중", 0.85),
        (f"{rs_period}일 수익률", 1.15),
    ]
    if spec["show_market_cap_column"] and "market_cap" in ranked.columns:
        columns.append(("시총(억)", 0.95))
    columns.append((spec["dv_label"], 1.0))

    widths = [c[1] for c in columns]
    container_key = f"scr_rank_table_{spec['code']}"

    with st.container(key=container_key):
        # 헤더
        header_cols = st.columns(widths, gap="small")
        for i, (label, _) in enumerate(columns):
            if i in (0, 5):
                align = "center"
            elif i in (2, 3):
                align = "left"
            else:
                align = "right"
            is_active = (
                (sort_col == "rs" and label == "RS")
                or (sort_col == "rs_weighted" and label == "RS가중")
            )
            style = f"text-align:{align};"
            if is_active:
                style += "color:#191f28; font-weight:700;"
            text = f"{label} ▼" if is_active else label
            header_cols[i].markdown(
                f"<div class='scr-rank-header' style='{style}'>{text}</div>",
                unsafe_allow_html=True,
            )

        # 데이터 행
        for row in ranked.itertuples(index=False):
            r = row._asdict()
            ticker = str(r["ticker"])
            name_raw = _first_valid_name(r.get("name_kr"), r.get("name_en"), ticker)
            below_ma5 = bool(r.get("below_ma5", False))
            name_display = f"{name_raw} :red[(이탈)]" if below_ma5 else name_raw

            rs_w = r.get("rs_weighted")
            return_n = r.get("return_n", 0) or 0
            up = return_n >= 0

            # 데이터 셀 — ★(0)와 추이(5) 제외한 컬럼들
            data_cells: list[str] = [
                str(int(r["rank"])),
                ticker,
                name_display,
                spec["price_chart_fmt"](r["last_price"]),
                _fmt_cell(r.get("rs"), "%.3f"),
                _fmt_cell(rs_w, "%.3f") if pd.notna(rs_w) else "—",
                _fmt_cell(return_n * 100.0, "%+.2f%%"),
            ]
            if spec["show_market_cap_column"] and "market_cap" in ranked.columns:
                mc = r.get("market_cap")
                data_cells.append(
                    _fmt_cell(mc / 1e8 if pd.notna(mc) else None, "%,.0f")
                )
            dv = r.get("avg_traded_value_20d")
            data_cells.append(_fmt_cell(
                dv / spec["dv_divisor"] if pd.notna(dv) else None,
                spec["dv_col_format"],
            ))

            row_cols = st.columns(widths, gap="small")

            # 0: 별표 토글
            is_fav = ticker in favs_set
            row_cols[0].button(
                "★" if is_fav else "☆",
                key=f"scr_rank_star_{spec['code']}_{ticker}",
                on_click=_make_fav_callback(spec, ticker),
                use_container_width=True,
            )

            # 1~4: 순위, 코드, 종목명, 현재가 (차트 픽)
            cb = _make_pick_callback(spec, ticker)
            for c_idx in (1, 2, 3, 4):
                row_cols[c_idx].button(
                    data_cells[c_idx - 1],
                    key=f"scr_rank_cell_{spec['code']}_{ticker}_{c_idx}",
                    on_click=cb,
                    use_container_width=True,
                )

            # 5: 스파크라인 (SVG, 시각만)
            tick_norm = ticker.upper() if spec["normalize_upper"] else ticker
            spark = _load_spark_data(tick_norm, days=22)
            row_cols[5].markdown(
                f"<div class='scr-rank-spark'>{_spark_svg(spark, up=up)}</div>",
                unsafe_allow_html=True,
            )

            # 6~끝: 나머지 데이터 셀
            for c_idx in range(6, len(widths)):
                row_cols[c_idx].button(
                    data_cells[c_idx - 2],
                    key=f"scr_rank_cell_{spec['code']}_{ticker}_{c_idx}",
                    on_click=cb,
                    use_container_width=True,
                )

    return st.session_state.get(_key(spec, "selected_ticker"))


# ─── 차트 패널 ──────────────────────────────────────────────────────

def _render_chart(
    spec: dict, ticker: str, lookback_days: int = 120, height: int = 620
) -> None:
    df = ui_load_chart_df(ticker, days=lookback_days + 70)

    if df is None or len(df) < 15:
        st.warning(
            f"**{ticker}** 차트를 그릴 데이터가 부족합니다 "
            f"(현재 {0 if df is None else len(df)}행, 15행 이상 필요). "
            f"사이드바의 **[{spec['refresh_btn']}]** 를 실행해주세요."
        )
        return

    ma5 = df["Close"].rolling(5).mean()
    ma20 = df["Close"].rolling(20).mean()
    ma60 = df["Close"].rolling(60).mean()
    atr9 = calc_wilder_atr(df["High"], df["Low"], df["Close"], period=9)

    df_view = df.tail(lookback_days)
    last_close = float(df_view["Close"].iloc[-1])
    last_date = df_view.index[-1].strftime("%Y-%m-%d")

    legend = "".join(
        f"<span style='display:inline-flex; align-items:center; "
        f"margin-right:12px;'>"
        f"<span style='display:inline-block; width:11px; height:11px; "
        f"border-radius:2px; background:{c}; margin-right:4px;'></span>"
        f"<span style='color:{COLOR_MUTED}; font-size:0.82rem;'>{lbl}</span>"
        f"</span>"
        for c, lbl in (
            (_COLOR_MA5, "MA5"),
            (_COLOR_MA20, "MA20"),
            (_COLOR_MA60, "MA60"),
        )
    )
    st.markdown(
        f"<div style='font-size:1.05rem; color:{COLOR_TEXT}; "
        f"margin:4px 0 2px 4px; font-weight:600;'>"
        f"{ticker} · {spec['price_chart_fmt'](last_close)} "
        f"<span style='color:{COLOR_MUTED}; font-weight:400; font-size:0.92rem;'>"
        f"({last_date})</span></div>"
        f"<div style='margin:0 0 6px 4px;'>{legend}</div>",
        unsafe_allow_html=True,
    )

    view_times = df_view.index.tz_localize("UTC")

    candle_df = pd.DataFrame({
        "time": view_times,
        "open": df_view["Open"].values,
        "high": df_view["High"].values,
        "low": df_view["Low"].values,
        "close": df_view["Close"].values,
    }).dropna()
    ohlc = candle_df[["open", "high", "low", "close"]]
    candle_df["high"] = ohlc.max(axis=1)
    candle_df["low"] = ohlc.min(axis=1)

    price_precision = int(spec.get("chart_price_precision", 2))
    price_min_move = float(spec.get("chart_price_min_move", 0.01))
    price_fmt_opts = PriceFormatOptions(
        type="price", precision=price_precision, min_move=price_min_move,
    )

    candle = CandlestickSeries(
        data=candle_df,
        column_mapping={
            "time": "time", "open": "open", "high": "high",
            "low": "low", "close": "close",
        },
        pane_id=0,
    )
    candle.up_color = _COLOR_UP
    candle.down_color = _COLOR_DOWN
    candle.border_up_color = _COLOR_UP
    candle.border_down_color = _COLOR_DOWN
    candle.wick_up_color = _COLOR_UP
    candle.wick_down_color = _COLOR_DOWN
    candle.price_format = price_fmt_opts

    def _line(
        series: pd.Series,
        color: str,
        pane: int,
        width: int = 2,
        price_fmt: PriceFormatOptions | None = None,
    ) -> LineSeries:
        s = series.reindex(df_view.index)
        line_df = pd.DataFrame({"time": view_times, "value": s.values}).dropna(subset=["value"])
        ls = LineSeries(
            data=line_df,
            column_mapping={"time": "time", "value": "value"},
            pane_id=pane,
        )
        ls.line_options = LineOptions(color=color, line_width=width, line_visible=True)
        if price_fmt is not None:
            ls.price_format = price_fmt
        return ls

    atr_fmt_opts = PriceFormatOptions(
        type="price", precision=price_precision, min_move=price_min_move,
    )

    series = [
        candle,
        _line(ma5, _COLOR_MA5, pane=0, price_fmt=price_fmt_opts),
        _line(ma20, _COLOR_MA20, pane=0, price_fmt=price_fmt_opts),
        _line(ma60, _COLOR_MA60, pane=0, price_fmt=price_fmt_opts),
        _line(atr9, _COLOR_ATR, pane=1, width=2, price_fmt=atr_fmt_opts),
    ]

    chart_opts = ChartOptions(
        height=height,
        layout=LayoutOptions(
            text_color=COLOR_TEXT,
            font_size=13,
            font_family=(
                "Pretendard, -apple-system, BlinkMacSystemFont, "
                "'Segoe UI', Roboto, sans-serif"
            ),
            pane_heights={
                0: PaneHeightOptions(factor=3.0),
                1: PaneHeightOptions(factor=1.0),
            },
        ),
        time_scale=TimeScaleOptions(time_visible=False, seconds_visible=False),
    )

    chart = Chart(series=series, options=chart_opts)
    chart.render(key=f"lwc_chart_{spec['code']}_{ticker}")

    _render_chart_metrics(spec, df, atr9)


def _render_chart_metrics(spec: dict, df: pd.DataFrame, atr9: pd.Series) -> None:
    last_close = float(df["Close"].iloc[-1])

    atr_last = atr9.dropna()
    if len(atr_last) > 0:
        atr_val = float(atr_last.iloc[-1])
        atr_pct = (atr_val / last_close * 100.0) if last_close > 0 else 0.0
        atr_display = spec["atr_fmt"](atr_val)
        atr_delta = f"{atr_pct:.2f}% of close"
    else:
        atr_display = "—"
        atr_delta = ""

    if len(df) >= 6:
        ret_5d = (df["Close"].iloc[-1] / df["Close"].iloc[-6] - 1.0) * 100.0
        ret_display = f"{ret_5d:+.2f}%"
    else:
        ret_display = "—"

    tv = df.get("traded_value")
    if tv is not None and tv.dropna().shape[0] > 0:
        avg_tv = float(tv.tail(20).mean()) / spec["dv_divisor"]
        dv_display = spec["dv_metric_fmt"](avg_tv)
    else:
        dv_display = "—"

    c1, c2, c3 = st.columns(3)
    c1.metric("9-day ATR", atr_display, atr_delta, delta_color="off")
    c2.metric("5일 수익률", ret_display)
    c3.metric("거래대금(20D 평균)", dv_display)


# ─── 섹션 엔트리 ────────────────────────────────────────────────────

def _render_screening_section(spec: dict, settings: tuple) -> None:
    index_code, rs_period, top_n, filter_config = settings

    tickers = ui_load_index_tickers(index_code)
    ranked, stats = ui_load_ranked_df(
        index_code=index_code,
        rs_period=rs_period,
        top_n=top_n,
        filter_config=filter_config,
        tickers_tuple=tuple(tickers),
    )

    idx_return = None
    if not ranked.empty and "index_return_n" in ranked.columns:
        idx_return = float(ranked["index_return_n"].iloc[0])

    col_left, col_right = st.columns([1.2, 1], gap="large")
    index_display = _index_display_name(index_code)

    with col_left:
        _render_rs_header(index_code, index_display, rs_period, top_n)
        _render_filter_summary(spec, filter_config)
        _render_pipeline_badge(stats, len(ranked))

        if stats.get("total", 0) == 0 or not tickers:
            st.warning(
                f"**{index_display}** 구성종목 데이터가 캐시에 없습니다. "
                f"사이드바의 **[{spec['refresh_btn']}]** 버튼을 눌러 "
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
            lag_excluded = stats.get("lag_excluded", 0)
            after_lag = stats.get("after_lag")
            if lag_excluded > 0 and after_lag == 0:
                st.warning(
                    f"필터 통과한 {lag_excluded}개 종목 모두의 시세 캐시가 "
                    f"**{index_display}** 지수보다 옛날 날짜에 머물러 있어, "
                    f"RS 시간 정합성 검사에서 전부 제외됐습니다. "
                    f"사이드바의 **[{spec['refresh_btn']}]** 을 눌러 "
                    f"시세 캐시를 최신화해주세요."
                )
                return
            idx_cache = cache_load_index(index_code, days=rs_period + 10)
            if idx_cache is None or idx_cache.empty or len(idx_cache) < rs_period + 1:
                st.warning(
                    f"**{index_display}** 지수 시세가 캐시에 없거나 부족합니다. "
                    f"사이드바에서 이 지수를 선택한 상태로 "
                    f"**[{spec['refresh_btn']}]** 를 눌러 지수 데이터를 받아주세요."
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

        selected_ticker = _render_ranking_table(spec, ranked, rs_period, index_code)
        if selected_ticker is not None:
            st.session_state[_key(spec, "selected_ticker")] = selected_ticker

    with col_right:
        st.markdown("### 차트 패널")
        # 검색 입력 중이면 검색 티커 우선, 없으면 랭킹 선택 티커
        search_val = st.session_state.get(_key(spec, "search_ticker"), "").strip()
        if search_val:
            chart_ticker = search_val.upper() if spec.get("normalize_upper", True) else search_val
        else:
            chart_ticker = st.session_state.get(_key(spec, "selected_ticker"))
        if chart_ticker:
            _render_chart(spec, str(chart_ticker), lookback_days=120)
        else:
            st.info(
                "좌측 테이블에서 종목을 선택하거나 "
                "티커를 검색하면 차트가 표시됩니다."
            )


# ─── 퍼블릭 엔트리 ─────────────────────────────────────────────────

def _render_remote_sync_badge() -> None:
    info = get_last_sync_info()

    if info is None:
        st.markdown(
            f"<div style='font-size:0.78rem; color:{COLOR_MUTED};'>"
            f"자동 갱신: <span style='color:#ff9500;'>원격 캐시 미확인</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        if info.status == "synced":
            color, label = COLOR_PROFIT, "방금 동기화"
        elif info.status == "up_to_date":
            color, label = "#10b981", "최신"
        elif info.status == "no_remote":
            color, label = "#ff9500", "원격 캐시 없음"
        elif info.status == "disabled":
            color, label = COLOR_MUTED, "동기화 꺼짐"
        else:
            color, label = COLOR_LOSS, info.status

        when = info.remote_kst or info.remote_stamp or "?"
        market = info.remote_market or ""
        market_str = f" · {market.upper()}" if market else ""
        st.markdown(
            f"<div style='font-size:0.78rem; color:{COLOR_MUTED}; line-height:1.35;'>"
            f"자동 갱신: <span style='color:{color}; font-weight:600;'>{label}</span><br>"
            f"<span style='color:{COLOR_MUTED};'>마지막: {when}{market_str}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    if st.button(
        "지금 원격 캐시 받기",
        width="stretch",
        key="scr_sync_now_btn",
        help=(
            "GitHub Actions 가 평일 정기적으로 갱신해 둔 캐시 DB 를 "
            "data-cache 브랜치에서 강제로 다시 받아옵니다. "
            "평소에는 앱 시작 시 자동으로 1회 동기화됩니다."
        ),
    ):
        with st.spinner("원격 캐시 다운로드 중…"):
            result = sync_from_remote(force=True)
        if result.status in ("synced", "up_to_date"):
            st.success(
                f"동기화 완료 ({result.status}) — {result.remote_kst or result.remote_stamp}"
            )
            st.cache_data.clear()
        elif result.status == "no_remote":
            st.warning("원격에 캐시가 아직 없습니다. (Actions 첫 실행 대기 중)")
        else:
            st.error(f"동기화 실패: {result.status} {result.error or ''}")


def render_screening_page() -> None:
    """미국주식 + 한국주식을 한 화면에 표시 (위: 미국, 아래: 한국).

    상단에 시장 요약 카드 2개 (US + KR) 가 함께 표시된다.
    """
    with st.sidebar:
        st.markdown("#### 주식 스크리닝")
        st.caption("상대강도(RS) 기반 종목 발굴")
        _render_remote_sync_badge()
        st.divider()
    us_settings = _render_sidebar(_US_SPEC)
    with st.sidebar:
        st.divider()
    kr_settings = _render_sidebar(_KR_SPEC)

    # ★ Step 1: 시장 요약 카드 (US + KR 나란히)
    st.markdown("### 📊 오늘의 시장")
    sum_cols = st.columns(2, gap="large")
    with sum_cols[0]:
        _render_market_card(_US_SPEC, us_settings)
    with sum_cols[1]:
        _render_market_card(_KR_SPEC, kr_settings)
    st.write("")

    st.markdown("## 미국주식")
    _render_screening_section(_US_SPEC, us_settings)

    st.divider()

    st.markdown("## 한국주식")
    _render_screening_section(_KR_SPEC, kr_settings)
