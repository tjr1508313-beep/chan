"""스크리닝 앱 UI 렌더링 함수.

통합 대비 규칙:
    - 모든 session_state 키는 `scr_` 접두사 사용 (예: `scr_rs_period`)
    - 화면 렌더링만 담당. RS 계산/필터링은 `screening.core`,
      데이터 조회는 `screening.data` 로 위임.
"""

import streamlit as st

# session_state 키 상수 (접두사 일관성 유지)
KEY_SELECTED_INDEX = "scr_selected_index"
KEY_RS_PERIOD = "scr_rs_period"
KEY_SELECTED_TICKER = "scr_selected_ticker"


def render_us_tab() -> None:
    """미국주식 스크리닝 탭."""
    # ───── 사이드바 (미국주식 탭 전용 설정) ─────
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
        selected_index_code = index_options[selected_index_label]

        st.slider(
            "RS 계산 기간 (일)",
            min_value=5,
            max_value=60,
            value=20,
            step=1,
            key=KEY_RS_PERIOD,
            help="RS = (종목 N일 수익률) / (지수 N일 수익률)",
        )

        st.caption(f"지수 코드: `{selected_index_code}`")

    # ───── 메인 영역 ─────
    col_left, col_right = st.columns([1, 1.2], gap="large")

    with col_left:
        st.markdown("### RS Top 20")
        st.info(
            "TODO: RS Top 20 테이블 (Phase 1.6)\n\n"
            "순위 / 티커 / 한글명 / 현재가 / RS 점수 / N일 수익률 / 거래대금"
        )
        st.caption("필터 적용 전후 종목 수 표시 예정: `3,500 → 247 → Top 20`")

    with col_right:
        st.markdown("### 차트 패널")
        st.info(
            "TODO: 차트 패널 (Phase 1.7)\n\n"
            "선택된 종목의 캔들스틱 + 5일 이평선 + 9일 ATR"
        )


def render_kr_tab() -> None:
    """한국주식 탭 (Phase 2 예정)."""
    st.info("한국주식은 Phase 2에서 지원 예정입니다.")


def render_crypto_tab() -> None:
    """코인 탭 (Phase 3 예정)."""
    st.info("코인은 Phase 3에서 지원 예정입니다.")
