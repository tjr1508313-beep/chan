"""스크리닝 앱 UI 렌더링.

미국주식 + 한국주식을 한 화면에 위/아래로 함께 표시한다.
자산군별 차이는 모듈 하단의 `_US_SPEC` / `_KR_SPEC` 두 dict 로 관리.
공통 렌더 함수들은 `spec` 인자를 받아 통화/포맷/배치함수/키 prefix 만 분기한다.

통합 대비 규칙:
    - session_state 키는 모두 `scr_` 접두사 (한국은 `scr_kr_*`).
    - 캐시 함수는 `ui_` 또는 `screen_` 접두사.
    - Streamlit 외부 의존성은 모두 import 시 명시.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pandas as pd
import streamlit as st
from lightweight_charts_pro.charts.options.line_options import LineOptions
from lightweight_charts_pro.charts.options.price_format_options import PriceFormatOptions
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
    cache_load_prices,
)
from .cache_sync import get_last_sync_info, has_auth_token, sync_from_remote
from .core import (
    calc_wilder_atr,
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
_COLOR_UP = COLOR_PROFIT       # #ff4b4b 캔들 양봉 (한국식)
_COLOR_DOWN = COLOR_LOSS        # #1a9cff 캔들 음봉
_COLOR_MA5 = "#ff9500"          # 5일 이평선 (주황) — 단기
_COLOR_MA20 = "#22c55e"         # 20일 이평선 (초록) — 중기
_COLOR_MA60 = "#a855f7"         # 60일 이평선 (보라) — 장기
_COLOR_ATR = "#6366f1"          # 9일 ATR (인디고) — 하단 패널

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
        meta_cols = filtered[["name_en", "name_kr", "avg_traded_value_20d", "market_cap"]]
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


# ─── 자산군 spec dict ───────────────────────────────────────────────
# 통화/포맷/배치함수/필터 UI/키 prefix 등 자산군 차이를 한 곳에서 관리.

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

    # 통화/포맷
    "currency": "$",
    "price_col_format": "$%.2f",
    "price_chart_fmt": lambda v: f"${v:,.2f}",
    "price_hover_fmt": "$%{y:,.2f}",
    "atr_fmt": lambda v: f"${v:,.2f}",
    # LWC 차트 가격 포맷 (우측 가격축, 캔들/선 라벨)
    "chart_price_precision": 2,
    "chart_price_min_move": 0.01,

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

    # 통화/포맷
    "currency": "₩",
    "price_col_format": "₩%,d",
    "price_chart_fmt": lambda v: f"₩{v:,.0f}",
    "price_hover_fmt": "₩%{y:,.0f}",
    "atr_fmt": lambda v: f"₩{v:,.0f}",
    # LWC 차트 가격 포맷 — 한국 주식은 정수 (소수점 표기 안 함)
    "chart_price_precision": 0,
    "chart_price_min_move": 1.0,

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

        # 데이터 새로고침 (백그라운드 스레드 — 미국/한국 독립 실행)
        _render_refresh_section(spec, index_code)

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
            "min_traded_value": spec["min_dv_to_raw"](min_dv),
            "min_market_cap": float(min_mc_raw),
            "max_daily_range_pct": float(max_range_pct) / 100.0,
            "max_atr_drop_multiple": float(atr_drop_mult) if exclude_atr_drop else 0.0,
            "exclude_china": bool(exclude_china),
            "exclude_risk": bool(exclude_risk),
        }

    return index_code, int(rs_period), int(top_n), filter_config


# ─── 새로고침 (백그라운드 스레드) ───────────────────────────────────
# 미국/한국 새로고침을 각각 별도 스레드로 돌려 서로 블로킹하지 않게 한다.
# 스레드는 `job` dict 만 변형하고 Streamlit API 는 호출하지 않는다
# (ScriptRunContext 불필요). 메인 스크립트는 fragment 로 job 을 폴링한다.

def _refresh_worker(
    spec: dict, index_code: str, target: list[str], force: bool, job: dict
) -> None:
    """백그라운드 스레드 본체 — 지수/시세/메타 갱신 후 `job` 에 결과 기록."""
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
            # 한국 메타는 프로세스 캐시 활용, 순차 처리로 충분
            meta_result = spec["refresh_meta_fn"](target, ttl_days=7, force=force)
            job["meta_done"] = len(target)
        job["messages"].append(
            f"메타: updated={meta_result['updated']}, "
            f"skipped={meta_result['skipped']}, "
            f"failed={len(meta_result['failed'])}"
        )
        job["phase"] = "완료"
    except Exception as e:  # 스레드 경계 — 예외를 job 에 담아 UI 로 전달
        job["error"] = str(e)
        job["phase"] = "실패"
    finally:
        job["running"] = False
        job["finished_at"] = time.time()


def _start_refresh(spec: dict, index_code: str, force: bool) -> None:
    """새로고침 백그라운드 스레드 시작. 이미 실행 중이면 무시."""
    job_key = _key(spec, "refresh_job")
    existing = st.session_state.get(job_key)
    if existing and existing.get("running"):
        return

    tickers = ui_load_index_tickers(index_code)
    if not tickers:
        st.session_state[job_key] = {
            "running": False,
            "phase": "실패",
            "error": "구성종목 리스트를 가져오지 못했습니다.",
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
    job: dict[str, Any] = {
        "running": True,
        "phase": "준비 중",
        "error": None,
        "messages": [],
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
    """진행 중 새로고침의 실시간 진행바."""
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
    """완료/실패한 새로고침 결과 표시."""
    # 완료 직후 1회만 랭킹 캐시 무효화
    if not job.get("cache_cleared"):
        ui_load_ranked_df.clear()
        job["cache_cleared"] = True

    if job.get("error"):
        st.error(f"새로고침 실패: {job['error']}")
        return
    st.success("새로고침 완료")
    for msg in job.get("messages", []):
        st.caption(msg)


@st.fragment(run_every=2)
def _refresh_progress_fragment(spec: dict) -> None:
    """진행 중 새로고침 폴링 fragment — Streamlit 이 2초마다 자동 재실행.

    완료 감지 시 1회만 full rerun 으로 부모를 다시 렌더 → 부모가
    `running=False` 이면 이 fragment 를 더는 호출하지 않으므로 Streamlit 이
    run_every 타이머를 자연 해제한다.
    """
    job = st.session_state.get(_key(spec, "refresh_job"))
    if not job:
        return
    if job.get("running"):
        _render_refresh_progress(spec, job)
        return
    # 완료 — 결과는 부모가 직접 렌더하도록 1회만 full rerun
    if not job.get("ui_finalized"):
        job["ui_finalized"] = True
        st.rerun(scope="app")


def _render_refresh_section(spec: dict, index_code: str) -> None:
    """데이터 새로고침 UI — 버튼 + 진행상황.

    미국/한국이 각각 자기 `job` 을 가지므로 서로 독립적으로 실행된다.
    진행 중일 때만 polling fragment 를 호출하고, 끝나면 결과 함수를
    직접 호출 → fragment 가 다음 풀-런에서 미렌더되어 타이머가 해제됨.
    """
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
    """필터 축소 흐름 배지 — '전체 → 주가 → … → 상위 N'."""
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
    # caption 의 폰트가 작아 한글이 흐릿하게 보이는 문제 → markdown 으로 키움.
    st.markdown(
        f"<div style='font-size:0.92rem; color:{COLOR_TEXT}; "
        f"margin-top:4px; margin-bottom:8px;'>"
        + " → ".join(parts)
        + "</div>",
        unsafe_allow_html=True,
    )


def _render_filter_summary(spec: dict, cfg: dict) -> None:
    """현재 필터 조건 한 줄 배지."""
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
        suffix = "*" if spec["code"] == "kr" else ""  # 한국은 데이터 미적용 표시
        badges.append(f"관리 제외{suffix}")
    # caption 의 폰트가 작아 한글이 흐릿하게 보이는 문제 → markdown 으로 키움.
    st.markdown(
        f"<div style='font-size:0.92rem; color:{COLOR_TEXT}; "
        f"margin-top:4px; margin-bottom:2px;'>"
        f"<span style='color:{COLOR_MUTED};'>필터:</span> "
        + " · ".join(badges)
        + "</div>",
        unsafe_allow_html=True,
    )


# ─── 랭킹 테이블 ─────────────────────────────────────────────────────

def _make_pick_callback(spec: dict, ticker: str):
    """행 셀 버튼 on_click 핸들러 — selected_ticker 를 즉시 세팅."""
    target_key = _key(spec, "selected_ticker")

    def _cb() -> None:
        st.session_state[target_key] = ticker

    return _cb


def _fmt_cell(value, fmt: str, na: str = "—") -> str:
    """안전 포맷 — NaN/None 이면 na 반환."""
    if value is None:
        return na
    try:
        if pd.isna(value):
            return na
    except (TypeError, ValueError):
        pass
    try:
        return fmt % value
    except (TypeError, ValueError):
        return str(value)


def _render_ranking_table(
    spec: dict, ranked: pd.DataFrame, rs_period: int
) -> str | None:
    """랭킹 테이블 — 각 셀이 투명 버튼이라 **행 어디든 클릭하면 차트가 열린다**.

    Streamlit st.dataframe 은 selection_mode 시에도 체크박스 클릭만 행 선택을
    트리거해 사용성이 떨어진다. 컬럼 너비/이탈 배지/행 클릭을 모두 만족시키기 위해
    `st.columns + st.button` 로 직접 렌더한다. 버튼 스타일은 theme.py 의 CSS 가
    셀처럼 보이도록 투명화한다.

    반환값은 호환을 위해 selected_ticker 를 그대로 반환 (외부에서 사용 안 해도 무방).
    """
    if ranked.empty:
        return None

    # (헤더 라벨, 컬럼 비율) — 모든 자산군 공통
    columns: list[tuple[str, float]] = [
        ("순위", 0.45),
        (spec["ticker_col_label"], 0.75),
        ("종목명", 2.2),
        ("현재가", 1.1),
        ("RS", 0.7),
        (f"{rs_period}일 수익률", 1.15),
    ]
    if spec["show_market_cap_column"] and "market_cap" in ranked.columns:
        columns.append(("시총(억)", 0.95))
    columns.append((spec["dv_label"], 1.0))

    widths = [c[1] for c in columns]
    container_key = f"scr_rank_table_{spec['code']}"

    with st.container(key=container_key):
        # 헤더 — 좌측 2·3번째는 left, 나머지는 right
        header_cols = st.columns(widths, gap="small")
        for i, (label, _) in enumerate(columns):
            align = "left" if i in (1, 2) else "right"
            header_cols[i].markdown(
                f"<div class='scr-rank-header' style='text-align:{align};'>{label}</div>",
                unsafe_allow_html=True,
            )

        # 데이터 행
        for row_pos, row in enumerate(ranked.itertuples(index=False)):
            r = row._asdict()
            ticker = str(r["ticker"])
            name_raw = r.get("name_kr") or r.get("name_en") or ticker
            below_ma5 = bool(r.get("below_ma5", False))
            # (이탈) 부분만 빨간색 — Streamlit 컬러 마크다운 (`:red[...]`) 사용
            name_display = f"{name_raw} :red[(이탈)]" if below_ma5 else name_raw

            cells: list[str] = [
                str(int(r["rank"])),
                ticker,
                name_display,
                spec["price_chart_fmt"](r["last_price"]),
                _fmt_cell(r.get("rs"), "%.3f"),
                _fmt_cell(r.get("return_n", 0) * 100.0, "%+.2f%%"),
            ]
            if spec["show_market_cap_column"] and "market_cap" in ranked.columns:
                mc = r.get("market_cap")
                mc_disp = _fmt_cell(mc / 1e8 if pd.notna(mc) else None, "%,.0f")
                cells.append(mc_disp)
            dv = r.get("avg_traded_value_20d")
            dv_disp = _fmt_cell(
                dv / spec["dv_divisor"] if pd.notna(dv) else None,
                spec["dv_col_format"],
            )
            cells.append(dv_disp)

            row_cols = st.columns(widths, gap="small")
            cb = _make_pick_callback(spec, ticker)
            for c_idx, cell_text in enumerate(cells):
                row_cols[c_idx].button(
                    cell_text,
                    key=f"scr_rank_cell_{spec['code']}_{row_pos}_{c_idx}",
                    on_click=cb,
                    use_container_width=True,
                )

    return st.session_state.get(_key(spec, "selected_ticker"))


# ─── 차트 패널 ───────────────────────────────────────────────────────

def _render_chart(spec: dict, ticker: str, lookback_days: int = 120) -> None:
    """선택된 티커의 캔들 + MA5/MA20/MA60 + 9ATR 패널 (TradingView lightweight-charts)."""
    # MA60 까지 그리려면 view 시작점 직전 60일 + 안전 버퍼 필요
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
    st.markdown(
        f"<div style='font-size:1.05rem; color:{COLOR_TEXT}; "
        f"margin:4px 0 6px 4px; font-weight:600;'>"
        f"{ticker} · {spec['price_chart_fmt'](last_close)} "
        f"<span style='color:{COLOR_MUTED}; font-weight:400; font-size:0.92rem;'>"
        f"({last_date})</span></div>",
        unsafe_allow_html=True,
    )

    candle_df = pd.DataFrame({
        "time": df_view.index,
        "open": df_view["Open"].values,
        "high": df_view["High"].values,
        "low": df_view["Low"].values,
        "close": df_view["Close"].values,
    }).dropna()
    # LWC 는 open/close 가 high/low 범위 밖이면 ValueValidationError 를 던진다.
    # FDR 한국 데이터에서 가끔 발생 — high/low 만 OHLC 4값 max/min 으로 보정 (open/close 보존).
    ohlc = candle_df[["open", "high", "low", "close"]]
    candle_df["high"] = ohlc.max(axis=1)
    candle_df["low"] = ohlc.min(axis=1)

    # 가격 포맷: 한국은 정수, 미국은 소수점 2자리
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
        line_df = pd.DataFrame({"time": s.index, "value": s.values}).dropna(subset=["value"])
        ls = LineSeries(
            data=line_df,
            column_mapping={"time": "time", "value": "value"},
            pane_id=pane,
        )
        ls.line_options = LineOptions(color=color, line_width=width, line_visible=True)
        if price_fmt is not None:
            ls.price_format = price_fmt
        return ls

    # ATR 패널도 통화에 맞춰 포맷 — 한국은 정수, 미국은 소수점 2자리
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
        height=620,
        layout=LayoutOptions(
            text_color=COLOR_TEXT,
            # 기본 11 → 13: x/y축 라벨이 너무 작아 보이는 문제 해결
            font_size=13,
            font_family=(
                "Pretendard, -apple-system, BlinkMacSystemFont, "
                "'Segoe UI', Roboto, sans-serif"
            ),
            # 가격(0) : ATR(1) ≈ 3 : 1
            pane_heights={
                0: PaneHeightOptions(factor=3.0),
                1: PaneHeightOptions(factor=1.0),
            },
        ),
    )

    chart = Chart(series=series, options=chart_opts)
    # 티커 전환 시 key 가 달라야 LWC 가 새 차트로 재마운트
    chart.render(key=f"lwc_chart_{spec['code']}_{ticker}")

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


# ─── 섹션 엔트리 ─────────────────────────────────────────────────────

def _render_screening_section(spec: dict, settings: tuple) -> None:
    """자산군 스크리닝 섹션 — 좌측 랭킹 + 우측 차트.

    사이드바는 `_render_sidebar` 가 별도로 그리며, 그 반환값을
    `settings` 로 받아 본문만 렌더한다.
    """
    index_code, rs_period, top_n, filter_config = settings

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

def _render_remote_sync_badge() -> None:
    """사이드바 상단 — 자동 갱신(원격 캐시) 마지막 동기화 정보."""
    info = get_last_sync_info()
    token_ok = has_auth_token()

    if info is None:
        if not token_ok:
            st.markdown(
                f"<div style='font-size:0.78rem; color:{COLOR_MUTED}; line-height:1.35;'>"
                f"자동 갱신: <span style='color:#ff9500;'>PAT 토큰 미설정</span><br>"
                f"<span style='color:{COLOR_MUTED};'>private 레포는 토큰 필요 — "
                f"<code>docs/auto-refresh-setup.md</code></span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<div style='font-size:0.78rem; color:{COLOR_MUTED};'>"
                f"자동 갱신: <span style='color:#ff9500;'>원격 캐시 미확인</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
    else:
        # status → 색상/문구
        if info.status == "synced":
            color, label = COLOR_PROFIT, "방금 동기화"
        elif info.status == "up_to_date":
            color, label = "#10b981", "최신"
        elif info.status == "no_remote":
            color, label = "#ff9500", "원격 캐시 없음"
        elif info.status == "auth_required":
            color, label = "#ff9500", "PAT 토큰 필요"
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
            st.cache_data.clear()  # 랭킹 캐시도 재계산
        elif result.status == "no_remote":
            st.warning("원격에 캐시가 아직 없습니다. (Actions 첫 실행 대기 중)")
        else:
            st.error(f"동기화 실패: {result.status} {result.error or ''}")


def render_screening_page() -> None:
    """미국주식 + 한국주식을 한 화면에 표시 (위: 미국, 아래: 한국).

    사이드바에는 두 자산군의 설정이 위아래로 함께 나열된다.
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

    st.markdown("## 미국주식")
    _render_screening_section(_US_SPEC, us_settings)

    st.divider()

    st.markdown("## 한국주식")
    _render_screening_section(_KR_SPEC, kr_settings)
