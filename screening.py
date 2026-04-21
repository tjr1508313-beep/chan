"""주식 스크리닝 웹 앱 (Streamlit 진입점).

Phase 1 — 미국주식 MVP. 한국주식/코인은 추후 Phase에서 지원.

통합 대비 규칙:
    - `st.set_page_config()`는 `main()` 함수 안에서만 호출
    - session_state 키는 모두 `scr_` 접두사 사용
    - CSS는 `screening.theme.apply_theme()`로 주입
    - 캐시 함수는 `us_` / `screen_` 접두사

통합 시 이 파일(`screening.py`)은 폐기되고 `screening/` 패키지만 매매일지 앱에
탭으로 붙일 예정.
"""

import streamlit as st

from screening.theme import apply_theme
from screening.ui import render_crypto_tab, render_kr_tab, render_us_tab


def main() -> None:
    st.set_page_config(
        page_title="주식 스크리닝",
        page_icon=":chart_with_upwards_trend:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_theme()

    st.title("주식 스크리닝")
    st.caption("상대강도(RS) 기반 종목 발굴 도구")

    tab_us, tab_kr, tab_crypto = st.tabs(
        ["🇺🇸 미국주식", "🇰🇷 한국주식", "🪙 코인"]
    )

    with tab_us:
        render_us_tab()

    with tab_kr:
        render_kr_tab()

    with tab_crypto:
        render_crypto_tab()


if __name__ == "__main__":
    main()
