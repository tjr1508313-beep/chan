"""주식 스크리닝 웹 앱 (Streamlit 진입점).

미국주식 + 한국주식을 한 화면에 위/아래로 함께 표시한다.

통합 대비 규칙:
    - `st.set_page_config()`는 `main()` 함수 안에서만 호출
    - session_state 키는 모두 `scr_` 접두사 사용
    - CSS는 `screening.theme.apply_theme()`로 주입
    - 캐시 함수는 `us_` / `screen_` 접두사

통합 시 이 파일(`screening.py`)은 폐기되고 `screening/` 패키지만 매매일지 앱에
탭으로 붙일 예정.
"""

import streamlit as st

from screening.auth import require_password
from screening.cache import init_cache
from screening.theme import apply_theme
from screening.ui import render_screening_page


def main() -> None:
    st.set_page_config(
        page_title="주식 스크리닝",
        page_icon=":chart_with_upwards_trend:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_theme()

    # 캐시 DB 가 없는 환경(새 체크아웃 등)에서도 읽기 경로가 깨지지 않도록 보장
    init_cache()

    # ─── 비밀번호 잠금 (배포 환경에서만 활성, 로컬은 자동 비활성) ───
    require_password()

    # ─── 본문: 미국주식 + 한국주식 한 화면 ───
    render_screening_page()


if __name__ == "__main__":
    main()
