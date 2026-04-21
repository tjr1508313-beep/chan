"""스크리닝 앱 테마/스타일.

통합 대비 규칙: 모든 CSS 주입은 `apply_theme()` 함수를 통해서만 수행.
매매일지와 병합 시 1회만 호출되도록 조정 가능.

색상 체계 (한국 주식 색상 규칙):
    - 배경  `#0e1117`
    - 카드  `#1e2130`
    - 수익  `#ff4b4b` (빨강)
    - 손실  `#1a9cff` (파랑)
"""

import streamlit as st

# 상수 — 다른 모듈에서 색상 일관성 유지용으로 import 가능
COLOR_BG = "#0e1117"
COLOR_CARD = "#1e2130"
COLOR_PROFIT = "#ff4b4b"
COLOR_LOSS = "#1a9cff"
COLOR_TEXT = "#fafafa"
COLOR_MUTED = "#a0a3b1"
COLOR_BORDER = "#2a2e3e"


_CSS = f"""
<style>
/* ───── 기본 배경/텍스트 ───── */
.stApp {{
    background-color: {COLOR_BG};
    color: {COLOR_TEXT};
}}

/* ───── 사이드바 ───── */
section[data-testid="stSidebar"] {{
    background-color: {COLOR_CARD};
    border-right: 1px solid {COLOR_BORDER};
}}

/* ───── 탭 ───── */
.stTabs [data-baseweb="tab-list"] {{
    gap: 4px;
    background-color: {COLOR_BG};
}}
.stTabs [data-baseweb="tab"] {{
    background-color: {COLOR_CARD};
    color: {COLOR_MUTED};
    border-radius: 6px 6px 0 0;
    padding: 8px 16px;
}}
.stTabs [aria-selected="true"] {{
    background-color: {COLOR_BG};
    color: {COLOR_TEXT};
    border-bottom: 2px solid {COLOR_PROFIT};
}}

/* ───── 카드/메트릭 ───── */
div[data-testid="stMetric"] {{
    background-color: {COLOR_CARD};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 12px 16px;
}}
div[data-testid="stMetricLabel"] {{
    color: {COLOR_MUTED};
    font-size: 0.85rem;
}}

/* ───── 버튼 ───── */
.stButton > button {{
    background-color: {COLOR_CARD};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    transition: all 0.15s ease-in-out;
}}
.stButton > button:hover {{
    border-color: {COLOR_PROFIT};
    color: {COLOR_PROFIT};
}}

/* ───── 테이블/데이터프레임 ───── */
div[data-testid="stDataFrame"] {{
    background-color: {COLOR_CARD};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
}}

/* ───── 입력 컨트롤 ───── */
.stSelectbox [data-baseweb="select"],
.stTextInput input,
.stNumberInput input {{
    background-color: {COLOR_CARD};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
}}

/* ───── 슬라이더 ───── */
.stSlider [data-baseweb="slider"] > div > div {{
    background-color: {COLOR_PROFIT};
}}
</style>
"""


def apply_theme() -> None:
    """스크리닝 앱 다크 테마 CSS를 Streamlit 페이지에 주입."""
    st.markdown(_CSS, unsafe_allow_html=True)
