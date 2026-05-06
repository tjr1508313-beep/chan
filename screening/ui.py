"""스크리닝 앱 UI 렌더링.

자산군별 차이는 모듈 하단의 `_US_SPEC` / `_KR_SPEC` 두 dict 로 관리.
공통 렌더 함수들은 `spec` 인자를 받아 통화/포맷/배치함수/키 prefix 만 분기한다.

통합 대비 규칙:
    - session_state 키는 모두 `scr_` 접두사 (한국은 `scr_kr_*`).
    - 캐시 함수는 `ui_` 또는 `screen_` 접두사.
    - Streamlit 외부 의존성은 모두 import 시 명시.
"""

from __future__ import annotations

from typing import Any

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
from .core import (
    screen_apply_filters,
    screen_build_screening_df,
    screen_filter_by_index_lag,
    screen_rank_rs,
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


# ─── 차트 색상 (자산군 무관) ────────────────────────────────────────────
_COLOR_UP = COLOR_PROFIT       # #ff4b4b
_COLOR_DOWN = COLOR_LOSS        # #1a9cff
_COLOR_MA = "#ff9500"           # 5일 이평선 (주황)
_COLOR_ATR = "#6366f1"          # 9일 ATR (인디고)
_COLOR_ATR_FILL = "rgba(99, 102, 241, 0.15)"

# 자산군 선택 키 (전역 — 자산군 무관)
KEY_ASSET_CLASS = "scr_asset_class"

# 지수 코드 → 사용자 친화 이름
_INDEX_DISPLAY = {
    "^IXIC": "나스닥",
    "^GSPC": "S&P 500",
    "KS11": "코스피",
    "KQ11": "코스닥",
}


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
    """필터 + RS 랭킹을 한 번에 돌려 (ranked_df, stats) 반환."""
    tickers = list(_tickers_tuple)
    if not tickers:
        return pd.DataFrame(), {"total": 0, "final": 0}

    df = screen_build_screening_df(tickers, lookback_days=20)
    filtered, stats = screen_apply_filters(df, filter_config)

    # 7) RS 시간 정합성 — 종목 마지막일이 지수와 0일 초과 어긋나면 제외
    passing, lag_excluded = screen_filter_by_index_lag(
        filtered.index.tolist(), index_code, max_lag_days=0
    )
    stats["lag_excluded"] = int(lag_excluded)
    stats["after_lag"] = int(len(passing))

    if not passing:
        return pd.DataFrame(), stats

    ranked = screen_rank_rs(passing, index_code, period=rs_period, top_n=top_n)
    if not ranked.empty:
        meta_cols = filtered[["name_en", "name_kr", "avg_dollar_volume_20d", "market_cap"]]
        ranked = ranked.merge(meta_cols, left_on="ticker", right_index=True, how="left")
    return ranked, stats


@st.cache_data(ttl=300, show_spinner=False)
def ui_load_chart_df(ticker: str, days: int) -> pd.DataFrame:
    """차트용 시세 로드 (캐시). 티커 전환 쾌적용."""
    return cache_load_prices(ticker, days=days)


# ─── 공통 헬퍼 ────────────────────────────────────────────────────────

def _index_display_name(index_code: str) -> str:
    return _INDEX_DISPLAY.get(index_code, index_code)


def _sort_tickers_stale_first(tickers: list[str], normalize_upper: bool) -> list[str]:
    """캐시 마지막일이 오래된(또는 캐시 없는) 티커가 앞으로 오도록 정렬.

    `target = tickers[:limit]` 흐름에서 stale 한 종목이 먼저 갱신되도록 보장.
    """
    last_dates = cache_get_all_last_price_dates()

    def key(t: str):
        lookup = t.upper() if normalize_upper else str(t)
        last = last_dates.get(lookup)
        return (last is not None, last or "")

    return sorted(tickers, key=key)


def _get_index_period_info(index_code: str, rs_period: int) -> dict | None:
    """지수 캐시에서 RS 산출 기준 정보(시작/종료 날짜·종가·변화율)."""
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


def _calc_wilder_atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 9
) -> pd.Series:
    """Wilder's ATR.

    TR_t  = max(H-L, |H - prevC|, |L - prevC|)
    ATR_t = (ATR_{t-1} * (period - 1) + TR_t) / period
    초기값: 첫 `period` 일의 TR 단순평균으로 부트스트랩.
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

    nan = float("nan")
    atr = pd.Series(nan, index=tr.index, dtype=float)
    if len(tr) < period:
        return atr

    initial = tr.iloc[1 : period + 1].mean()
    atr.iloc[period] = initial
    for i in range(period + 1, len(tr)):
        prev_atr = atr.iloc[i - 1]
        tr_i = tr.iloc[i]
        if pd.isna(prev_atr) or pd.isna(tr_i):
            continue
        atr.iloc[i] = (prev_atr * (period - 1) + tr_i) / period
    return atr


# ─── 자산군 spec dict ───────────────────────────────────────────────
# 통화/포맷/배치함수/필터 UI/키 prefix 등 자산군 차이를 한 곳에서 관리.
# Phase 3 코인 추가 시 _CRYPTO_SPEC 만 새로 정의.

_US_SPEC: dict[str, Any] = {
    "code": "us",
    "label": "미국주식",
    "indices": {"나스닥": "^IXIC", "S&P 500": "^GSPC"},
    "key_prefix": "scr",
    "normalize_upper": True,

    # 새로고침
    "refresh_data_label": "yfinance",
    "refresh_btn": "yfinance에서 내려받기",
    "refresh_btn_help": (
        "지수 + 선두 N개 구성종목의 시세/메타를 yfinance 에서 내려받아 "
        "로컬 SQLite 에 저장합니다. 앱은 이 DB만 읽으므로 최신 시세를 "
        "반영하려면 이 버튼을 눌러야 합니다."
    ),
    "refresh_help": (
        "yfinance 에서 한 번에 받아올 종목 수. "
        "나스닥 전체(3800+)는 30분 이상 걸림. "
        "테스트/점진 확장용으로 제한 가능."
    ),
    "refresh_max": 4000,
    "refresh_index_fn": screen_refresh_index,
    "refresh_prices_fn": screen_refresh_prices,
    "refresh_meta_fn": screen_refresh_meta,
    "sleep_prices": 0.2,
    "sleep_meta": 0.3,
    "force_help": (
        "이전 캐시를 덮어쓰고 yfinance 에서 다시 받음. 분할/spin-off 등 "
        "corporate action 이후 historical 가격이 retroactively 재조정된 "
        "경우 이 옵션으로 정합성 복구."
    ),

    # 통화/포맷
    "currency": "$",
    "price_col_format": "$%.2f",
    "price_chart_fmt": lambda v: f"${v:,.2f}",
    "price_hover_fmt": "$%{y:,.2f}",
    "atr_fmt": lambda v: f"${v:,.2f}",

    # 거래대금
    "dv_label": "거래대금(M$)",
    "dv_divisor": 1_000_000.0,
    "dv_col_format": "%.1f",
    "dv_metric_fmt": lambda v: f"${v:,.1f}M",

    # 시총
    "show_market_cap_column": False,

    # 필터 UI
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

    "extra_caption": None,
    "ticker_col_label": "티커",
}

_KR_SPEC: dict[str, Any] = {
    "code": "kr",
    "label": "한국주식",
    "indices": {"코스피": "KS11", "코스닥": "KQ11"},
    "key_prefix": "scr_kr",
    "normalize_upper": False,

    # 새로고침
    "refresh_data_label": "FDR",
    "refresh_btn": "FDR에서 내려받기",
    "refresh_btn_help": (
        "지수 + 선두 N개 구성종목의 시세/메타를 FinanceDataReader 에서 "
        "내려받아 로컬 SQLite 에 저장합니다."
    ),
    "refresh_help": (
        "FinanceDataReader 에서 한 번에 받아올 종목 수. "
        "코스피 전체(950)는 5분, 코스닥 전체(1800)는 10분 안팎."
    ),
    "refresh_max": 2900,
    "refresh_index_fn": screen_refresh_index_kr,
    "refresh_prices_fn": screen_refresh_prices_kr,
    "refresh_meta_fn": screen_refresh_meta_kr,
    "sleep_prices": 0.1,
    "sleep_meta": 0.0,
    "force_help": (
        "이전 캐시를 덮어쓰고 FDR 에서 다시 받음. 분할/액면분할 등 이후 "
        "historical 가격이 retroactively 재조정된 경우 정합성 복구용."
    ),

    # 통화/포맷
    "currency": "₩",
    "price_col_format": "₩%,d",
    "price_chart_fmt": lambda v: f"₩{v:,.0f}",
    "price_hover_fmt": "₩%{y:,.0f}",
    "atr_fmt": lambda v: f"₩{v:,.0f}",

    # 거래대금
    "dv_label": "거래대금(억)",
    "dv_divisor": 100_000_000.0,
    "dv_col_format": "%,.0f",
    "dv_metric_fmt": lambda v: f"{v:,.0f}억",

    # 시총 (한국 전용)
    "show_market_cap_column": True,

    # 필터 UI
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

    # 한국 전용: 시총 필터 슬라이더
    "show_market_cap_filter": True,
    "min_marketcap_label": "최소 시가총액 (억 원)",
    "min_marketcap_default": 3_000,
    "min_marketcap_max": 10_000_000,
    "min_marketcap_step": 500,
    "min_marketcap_help": "시가총액이 너무 작은 종목 배제. 사용자 결정 기본 3,000억.",
    "min_marketcap_to_raw": lambda v: v * 100_000_000.0,
    "min_marketcap_summary_fmt": lambda raw: f"시총 ≥ {raw/100_000_000:,.0f}억",

    "show_china_filter": False,

    "extra_caption": "✓ 모집단 단계에서 우선주/리츠/ETF/스팩/외국기업은 자동 제외됨",
    "ticker_col_label": "코드",
}


def _key(spec: dict, suffix: str) -> str:
    """spec 별 session_state 키 생성 — `f"{prefix}_{suffix}"`."""
    return f"{spec['key_prefix']}_{suffix}"


# ─── 사이드바 ────────────────────────────────────────────────────────

def render_asset_selector() -> str:
    """사이드바 최상단 자산군 선택 → `"us"` / `"kr"` / `"crypto"`."""
    with st.sidebar:
        st.markdown("#### 주식 스크리닝")
        st.caption("상대강도(RS) 기반 종목 발굴")

        labels_to_code = {"미국주식": "us", "한국주식": "kr", "코인": "crypto"}
        current_label = st.session_state.get(f"{KEY_ASSET_CLASS}_label", "미국주식")

        selected = st.pills(
            "자산군",
            options=list(labels_to_code.keys()),
            default=current_label,
            label_visibility="collapsed",
            key=f"{KEY_ASSET_CLASS}_label",
        )
        if selected is None:
            selected = current_label

        code = labels_to_code.get(selected, "us")
        st.session_state[KEY_ASSET_CLASS] = code
        st.divider()
        return code


def _render_index_status_badge(index_code: str) -> None:
    """사이드바 미니 배지: 지수 캐시 보유 여부."""
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


def _render_sidebar(spec: dict) -> tuple[str, int, int, int, dict]:
    """자산군 사이드바 → (index_code, rs_period, top_n, refresh_limit, filter_config)."""
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

        # 데이터 새로고침
        st.divider()
        st.markdown("##### 데이터 새로고침")
        refresh_limit = st.number_input(
            "이번에 받을 종목 수",
            min_value=10, max_value=spec["refresh_max"], value=200, step=50,
            key=_key(spec, "refresh_limit"),
            help=spec["refresh_help"],
        )
        force_refresh = st.checkbox(
            "캐시 무시하고 전부 새로 받기 (force)",
            value=False,
            key=_key(spec, "force_refresh"),
            help=spec["force_help"],
        )
        if st.button(
            spec["refresh_btn"], width="stretch", help=spec["refresh_btn_help"]
        ):
            _run_refresh(spec, index_code, int(refresh_limit), force=bool(force_refresh))

        # 필터 설정
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
            exclude_china = False
            if spec["show_china_filter"]:
                exclude_china = st.checkbox(
                    "중국기업 제외", value=True,
                    key=_key(spec, "filter_exclude_china"),
                )
            exclude_risk = st.checkbox(
                "관리/위험종목 제외", value=True,
                key=_key(spec, "filter_exclude_risk"),
                help=(
                    "KRX 공시 기반 관리종목/투자주의/거래정지 제외. "
                    "위험종목 데이터를 사이드바 새로고침에서 갱신해야 효과가 적용됩니다."
                    if spec["code"] == "kr" else None
                ),
            )
            if spec["extra_caption"]:
                st.caption(spec["extra_caption"])

        filter_config = {
            "min_price": float(min_price),
            "min_dollar_volume": spec["min_dv_to_raw"](min_dv),
            "min_market_cap": float(min_mc_raw),
            "max_daily_range_pct": float(max_range_pct) / 100.0,
            "exclude_china": bool(exclude_china),
            "exclude_risk": bool(exclude_risk),
        }

    return index_code, int(rs_period), int(top_n), int(refresh_limit), filter_config


# ─── 새로고침 ────────────────────────────────────────────────────────

def _run_refresh(spec: dict, index_code: str, limit: int, force: bool) -> None:
    """캐시 새로고침 — 지수 + 구성종목 상위 limit 개의 시세/메타 갱신."""
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
            tickers = _sort_tickers_stale_first(
                tickers, normalize_upper=spec["normalize_upper"]
            )
            target = tickers[:limit]
            st.write(
                f"   → 총 {len(tickers)}개 중 선두(stale 우선) {len(target)}개 대상"
                + (" · force=True" if force else "")
            )

            st.write("2) 지수 시세 갱신")
            idx_result = spec["refresh_index_fn"](index_code, days=300, force=force)
            st.write(f"   → {idx_result}")

            sleep_p = spec["sleep_prices"]
            st.write(f"3) 종목 시세 갱신 ({len(target)}건, sleep {sleep_p}s/건)")
            with st.spinner(f"{spec['refresh_data_label']} 호출 중..."):
                px_result = spec["refresh_prices_fn"](
                    target, days=300, force=force, sleep_sec=sleep_p
                )
            px_parts = [
                f"updated={px_result['updated']}",
                f"skipped={px_result['skipped']}",
                f"failed={len(px_result['failed'])}",
            ]
            # 미국 batch 는 분할 자동 감지로 force 재다운로드 카운트 노출 (한국은 키 없음)
            fr = px_result.get("force_refetched", 0)
            if fr:
                px_parts.append(f"분할재요청={fr}")
            st.write("   → " + ", ".join(px_parts))

            st.write(f"4) 메타데이터 갱신 ({len(target)}건)")
            with st.spinner(f"{spec['refresh_data_label']} 메타 조회 중..."):
                # 미국 batch 는 sleep_sec 인자, 한국도 동일 시그니처.
                meta_result = spec["refresh_meta_fn"](
                    target, ttl_days=7, force=force, sleep_sec=spec["sleep_meta"]
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


# ─── 헤더/배지/필터 요약 ───────────────────────────────────────────

def _render_rs_header(
    index_code: str, index_display: str, rs_period: int, top_n: int
) -> None:
    """헤더: 'RS Top N' + 지수 N일 변화율/시작·종료 정보."""
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
    """필터 축소 흐름 배지 — '전체 → 주가 → … → Top N'."""
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
    lag_excluded = stats.get("lag_excluded", 0)
    if lag_excluded:
        parts.append(f"지연 -{lag_excluded}")
    parts.append(f"Top {ranked_len}")
    st.caption(" → ".join(parts))


def _render_filter_summary(spec: dict, cfg: dict) -> None:
    """현재 필터 조건 한 줄 배지."""
    badges = [
        f"주가 {spec['min_price_summary_fmt'](cfg['min_price'])}",
        f"거래대금 {spec['min_dv_summary_fmt'](cfg['min_dollar_volume'])}",
    ]
    min_mc = cfg.get("min_market_cap", 0)
    if min_mc > 0 and "min_marketcap_summary_fmt" in spec:
        badges.append(spec["min_marketcap_summary_fmt"](min_mc))
    badges.append(f"변동폭 < {cfg['max_daily_range_pct']*100:.0f}%")
    if spec["show_china_filter"] and cfg.get("exclude_china"):
        badges.append("중국 제외")
    if cfg.get("exclude_risk"):
        suffix = "*" if spec["code"] == "kr" else ""  # 한국은 데이터 미적용 표시
        badges.append(f"관리 제외{suffix}")
    st.caption("필터: " + " · ".join(badges))


# ─── 랭킹 테이블 ─────────────────────────────────────────────────────

def _render_ranking_table(
    spec: dict, ranked: pd.DataFrame, rs_period: int
) -> str | None:
    """랭킹 테이블 + 선택된 티커 반환(없으면 None)."""
    if ranked.empty:
        return None

    # 수익률은 소수(1.05 = 105%) → % 단위로 100배 변환
    display = pd.DataFrame({
        "순위": ranked["rank"],
        spec["ticker_col_label"]: ranked["ticker"],
        "종목명": ranked.apply(
            lambda r: r.get("name_kr") or r.get("name_en") or r["ticker"], axis=1,
        ),
        "현재가": ranked["last_price"],
        "RS": ranked["rs"],
        f"{rs_period}일 수익률": ranked["return_n"] * 100.0,
    })

    column_config: dict[str, Any] = {
        "순위": st.column_config.NumberColumn(width="small"),
        spec["ticker_col_label"]: st.column_config.TextColumn(width="small"),
        "종목명": st.column_config.TextColumn(width="medium"),
        "현재가": st.column_config.NumberColumn(format=spec["price_col_format"]),
        "RS": st.column_config.NumberColumn(format="%.3f"),
        f"{rs_period}일 수익률": st.column_config.NumberColumn(format="%+.2f%%"),
    }

    # 시총 컬럼 (한국만)
    if spec["show_market_cap_column"] and "market_cap" in ranked.columns:
        display["시총(억)"] = ranked["market_cap"] / 100_000_000.0
        column_config["시총(억)"] = st.column_config.NumberColumn(format="%,.0f")

    # 거래대금
    dv_label = spec["dv_label"]
    if "avg_dollar_volume_20d" in ranked.columns:
        display[dv_label] = ranked["avg_dollar_volume_20d"] / spec["dv_divisor"]
    else:
        display[dv_label] = pd.Series([float("nan")] * len(ranked))
    column_config[dv_label] = st.column_config.NumberColumn(format=spec["dv_col_format"])

    event = st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        height=min(600, 45 + 35 * len(display)),
        on_select="rerun",
        selection_mode="single-row",
        key=_key(spec, "selected_row"),
        column_config=column_config,
    )

    selected_rows = event.selection.rows if hasattr(event, "selection") else []
    if selected_rows:
        idx = selected_rows[0]
        if 0 <= idx < len(ranked):
            return str(ranked.iloc[idx]["ticker"])
    return None


# ─── 차트 패널 ───────────────────────────────────────────────────────

def _render_chart(spec: dict, ticker: str, lookback_days: int = 120) -> None:
    """선택된 티커의 캔들 + 5MA + 9ATR 차트."""
    df = ui_load_chart_df(ticker, days=lookback_days + 10)

    if df is None or len(df) < 15:
        st.warning(
            f"**{ticker}** 차트를 그릴 데이터가 부족합니다 "
            f"(현재 {0 if df is None else len(df)}행, 15행 이상 필요). "
            f"사이드바의 **[{spec['refresh_btn']}]** 를 실행해주세요."
        )
        return

    ma5 = df["Close"].rolling(5).mean()
    atr9 = _calc_wilder_atr(df["High"], df["Low"], df["Close"], period=9)

    df_view = df.tail(lookback_days)
    ma5_view = ma5.reindex(df_view.index)
    atr9_view = atr9.reindex(df_view.index)

    last_close = float(df_view["Close"].iloc[-1])
    last_date = df_view.index[-1].strftime("%Y-%m-%d")
    title = f"{ticker} · {spec['price_chart_fmt'](last_close)} ({last_date})"

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.7, 0.3], vertical_spacing=0.05,
        subplot_titles=("", "9-day ATR (Wilder)"),
    )
    fig.add_trace(
        go.Candlestick(
            x=df_view.index,
            open=df_view["Open"], high=df_view["High"],
            low=df_view["Low"], close=df_view["Close"],
            name="OHLC",
            increasing_line_color=_COLOR_UP, increasing_fillcolor=_COLOR_UP,
            decreasing_line_color=_COLOR_DOWN, decreasing_fillcolor=_COLOR_DOWN,
            showlegend=False,
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df_view.index, y=ma5_view, name="MA5",
            line=dict(color=_COLOR_MA, width=1.8),
            hovertemplate=f"MA5: {spec['price_hover_fmt']}<extra></extra>",
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df_view.index, y=atr9_view, name="ATR9",
            line=dict(color=_COLOR_ATR, width=1.5),
            fill="tozeroy", fillcolor=_COLOR_ATR_FILL,
            hovertemplate=f"ATR9: {spec['price_hover_fmt']}<extra></extra>",
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
    fig.update_yaxes(
        title_text=f"Price ({spec['currency']})", row=1, col=1,
        tickfont=dict(color=COLOR_MUTED),
    )
    fig.update_yaxes(title_text="ATR", row=2, col=1, tickfont=dict(color=COLOR_MUTED))

    st.plotly_chart(fig, width="stretch", theme=None)
    _render_chart_metrics(spec, df, atr9)


def _render_chart_metrics(spec: dict, df: pd.DataFrame, atr9: pd.Series) -> None:
    """차트 하단 3칸 메트릭: ATR, 5일 수익률, 20일 평균 거래대금."""
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

    dv = df.get("dollar_volume")
    if dv is not None and dv.dropna().shape[0] > 0:
        avg_dv = float(dv.tail(20).mean()) / spec["dv_divisor"]
        dv_display = spec["dv_metric_fmt"](avg_dv)
    else:
        dv_display = "—"

    c1, c2, c3 = st.columns(3)
    c1.metric("9-day ATR", atr_display, atr_delta, delta_color="off")
    c2.metric("5일 수익률", ret_display)
    c3.metric("거래대금(20D 평균)", dv_display)


# ─── 탭 엔트리 ───────────────────────────────────────────────────────

def _render_screening_tab(spec: dict) -> None:
    """공통 스크리닝 탭 — 사이드바 + 좌측 랭킹 + 우측 차트."""
    index_code, rs_period, top_n, _refresh_limit, filter_config = _render_sidebar(spec)

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
    index_display = _index_display_name(index_code)

    with col_left:
        _render_rs_header(index_code, index_display, rs_period, top_n)
        _render_filter_summary(spec, filter_config)
        _render_pipeline_badge(stats, len(ranked))

        # 빈 상태 분기
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

        selected_ticker = _render_ranking_table(spec, ranked, rs_period)
        if selected_ticker is not None:
            st.session_state[_key(spec, "selected_ticker")] = selected_ticker

    with col_right:
        st.markdown("### 차트 패널")
        selected = st.session_state.get(_key(spec, "selected_ticker"))
        if selected:
            _render_chart(spec, str(selected), lookback_days=120)
        else:
            st.info(
                "좌측 테이블에서 종목을 선택하면 "
                "캔들스틱 + 5일 이평선 + 9일 ATR 차트가 표시됩니다."
            )


# ─── 퍼블릭 엔트리 ─────────────────────────────────────────────────

def render_us_tab() -> None:
    """미국주식 스크리닝 탭."""
    _render_screening_tab(_US_SPEC)


def render_kr_tab() -> None:
    """한국주식 스크리닝 탭."""
    _render_screening_tab(_KR_SPEC)


def render_crypto_tab() -> None:
    """코인 탭 (Phase 3 예정)."""
    st.info("코인은 Phase 3에서 지원 예정입니다.")
