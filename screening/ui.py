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
from .cache import cache_load_prices
from .core import screen_apply_filters, screen_build_screening_df, screen_rank_rs
from .data import us_get_nasdaq_tickers, us_get_sp500_tickers
from .theme import COLOR_BG, COLOR_LOSS, COLOR_MUTED, COLOR_PROFIT, COLOR_TEXT


# ─── 차트 색상 (나중에 theme.py 로 이관 예정) ────────────────────────────
# 한국식 색상 체계: 상승=빨강, 하락=파랑
_COLOR_UP = COLOR_PROFIT       # #ff4b4b
_COLOR_DOWN = COLOR_LOSS        # #1a9cff
_COLOR_MA = "#ffa726"           # 5일 이평선 (주황)
_COLOR_ATR = "#8b80f9"          # 9일 ATR (보라)
_COLOR_ATR_FILL = "rgba(139, 128, 249, 0.18)"  # ATR 음영


# ─── session_state 키 상수 (접두사 일관성) ────────────────────────────
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


# ─── 데이터 획득 (캐시된 헬퍼) ─────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def ui_load_index_tickers(index_code: str) -> list[str]:
    """지수 구성종목 티커 리스트. FDR 호출 비용 있어 1시간 캐시."""
    if index_code == "^IXIC":
        return us_get_nasdaq_tickers()
    if index_code == "^GSPC":
        return us_get_sp500_tickers()
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
        # 메타(한글명/영문명) 붙이기
        meta_cols = filtered[["name_en", "name_kr", "avg_dollar_volume_20d"]]
        if not ranked.empty:
            ranked = ranked.merge(
                meta_cols, left_on="ticker", right_index=True, how="left"
            )

    return ranked, stats


# ─── 렌더링 헬퍼 ────────────────────────────────────────────────────

def _render_sidebar() -> tuple[str, int, int, int, dict]:
    """사이드바 렌더링 → (index_code, rs_period, top_n, refresh_limit, filter_config)."""
    with st.sidebar:
        st.subheader("미국주식 설정")

        index_options = {
            "나스닥 (^IXIC)": "^IXIC",
            "S&P 500 (^GSPC)": "^GSPC",
        }
        selected_index_label = st.selectbox(
            "지수 선택",
            options=list(index_options.keys()),
            index=0,
            key=KEY_SELECTED_INDEX,
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
            "Top N",
            min_value=10,
            max_value=50,
            value=20,
            step=5,
            key=KEY_TOP_N,
        )

        st.caption(f"지수 코드: `{index_code}`")

        # ─── 캐시 새로고침 ───
        st.divider()
        st.subheader("캐시 새로고침")
        refresh_limit = st.number_input(
            "이번 새로고침 대상 종목 수 제한",
            min_value=10,
            max_value=4000,
            value=200,
            step=50,
            key=KEY_REFRESH_LIMIT,
            help=(
                "yfinance 풀배치는 수십 분 걸림. "
                "테스트/점진 확장용으로 티커 수를 제한."
            ),
        )
        refresh_clicked = st.button(
            "현재 지수 캐시 새로고침",
            use_container_width=True,
            help=(
                "지수 + 선두 N개 구성종목의 시세/메타를 yfinance 에서 내려받아 "
                "SQLite 캐시에 저장합니다. 매우 느립니다."
            ),
        )
        if refresh_clicked:
            _run_refresh(index_code, int(refresh_limit))

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


def _run_refresh(index_code: str, limit: int) -> None:
    """캐시 새로고침 — 지수 + 구성종목 상위 limit 개의 시세/메타 갱신."""
    with st.status(f"{index_code} 캐시 새로고침 시작 …", expanded=True) as status:
        try:
            st.write("1) 구성종목 리스트 로드")
            tickers = ui_load_index_tickers(index_code)
            if not tickers:
                status.update(label="구성종목을 가져오지 못함", state="error")
                return
            target = tickers[:limit]
            st.write(f"   → 총 {len(tickers)}개 중 선두 {len(target)}개 대상")

            st.write("2) 지수 시세 갱신")
            idx_result = screen_refresh_index(index_code, days=300)
            st.write(f"   → {idx_result}")

            st.write(f"3) 종목 시세 갱신 (sleep 0.2s/건 — {len(target)}건)")
            with st.spinner("yfinance 호출 중..."):
                px_result = screen_refresh_prices(target, days=300, sleep_sec=0.2)
            st.write(
                f"   → updated={px_result['updated']}, "
                f"skipped={px_result['skipped']}, "
                f"failed={len(px_result['failed'])}"
            )

            st.write(f"4) 메타데이터 갱신 (sleep 0.3s/건 — {len(target)}건)")
            with st.spinner("yfinance Ticker.info 호출 중..."):
                meta_result = screen_refresh_meta(target, ttl_days=7, sleep_sec=0.3)
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
    """필터 축소 흐름 배지 — '3500 → 2800 → ... → 800 → Top N'."""
    total = stats.get("total", 0)
    if total == 0:
        return
    parts = [
        f"전체 {total}",
        f"주가 {stats.get('after_price', 0)}",
        f"거래대금 {stats.get('after_volume', 0)}",
        f"관리 {stats.get('after_risk', 0)}",
        f"중국 {stats.get('after_china', 0)}",
        f"변동성 {stats.get('after_volatility', 0)}",
        f"Top {ranked_len}",
    ]
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
            f"{rs_period}일 수익률": ranked["return_n"],
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
        use_container_width=True,
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
            "사이드바의 **[현재 지수 캐시 새로고침]** 을 실행해주세요."
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
        paper_bgcolor=COLOR_BG,
        plot_bgcolor=COLOR_BG,
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

    # 축 스타일
    grid_color = "rgba(255,255,255,0.06)"
    fig.update_xaxes(showgrid=True, gridcolor=grid_color, zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor=grid_color, zeroline=False)
    fig.update_yaxes(title_text="Price ($)", row=1, col=1, tickfont=dict(color=COLOR_MUTED))
    fig.update_yaxes(title_text="ATR", row=2, col=1, tickfont=dict(color=COLOR_MUTED))

    st.plotly_chart(fig, use_container_width=True, theme=None)

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
        header_cols = st.columns([2, 1])
        with header_cols[0]:
            st.markdown(f"### RS Top {top_n}")
        with header_cols[1]:
            if idx_return is not None:
                sign = "+" if idx_return >= 0 else ""
                color = COLOR_PROFIT if idx_return >= 0 else COLOR_LOSS
                st.markdown(
                    f"<div style='text-align:right; color:{color}; "
                    f"font-weight:600; padding-top:8px;'>"
                    f"지수 {rs_period}일 수익률: {sign}{idx_return*100:.2f}%"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        _render_filter_summary(filter_config)
        _render_pipeline_badge(stats, len(ranked))

        # ─── 빈 상태 분기 ───
        if stats.get("total", 0) == 0 or not tickers:
            st.warning(
                "캐시 데이터가 비어있거나 구성종목 리스트가 없습니다. "
                "사이드바의 **[현재 지수 캐시 새로고침]** 버튼을 눌러 "
                "데이터를 채워주세요."
            )
            return

        if stats.get("final", 0) == 0:
            st.warning(
                "필터 조건에 맞는 종목이 없습니다. "
                "사이드바의 **필터 설정** 을 완화해보세요."
            )
            return

        if ranked.empty:
            # final > 0 인데 ranked 가 비었다 = 지수 수익률 0 근처
            st.warning(
                f"지수({index_code}) {rs_period}일 변동폭이 너무 작아 "
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


def render_kr_tab() -> None:
    """한국주식 탭 (Phase 2 예정)."""
    st.info("한국주식은 Phase 2에서 지원 예정입니다.")


def render_crypto_tab() -> None:
    """코인 탭 (Phase 3 예정)."""
    st.info("코인은 Phase 3에서 지원 예정입니다.")
