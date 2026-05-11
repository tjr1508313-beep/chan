"""스크리닝 앱 테마/스타일 (라이트 모드).

통합 대비 규칙: 모든 CSS 주입은 `apply_theme()` 함수를 통해서만 수행.
매매일지와 병합 시 1회만 호출되도록 조정 가능.

색상 체계 (한국 주식 색상 규칙):
    - 배경       `#f7f8fa` (아주 밝은 회색)
    - 카드       `#ffffff` (순백)
    - 수익       `#ff4b4b` (빨강)
    - 손실       `#1a9cff` (파랑)
    - 본문 텍스트 `#1a1a1a`
    - 서브 텍스트 `#6b7280`
    - 테두리      `#e5e7eb`
"""

import streamlit as st

# 상수 — 다른 모듈에서 색상 일관성 유지용으로 import 가능
COLOR_BG = "#f7f8fa"
COLOR_CARD = "#ffffff"
COLOR_PROFIT = "#ff4b4b"
COLOR_LOSS = "#1a9cff"
COLOR_TEXT = "#1a1a1a"
COLOR_MUTED = "#6b7280"
COLOR_BORDER = "#e5e7eb"
COLOR_HOVER = "#f1f3f7"
COLOR_ACCENT = "#ff4b4b"


_CSS = f"""
<style>
/* ───── 한글 폰트 (Pretendard — 자모 가독성 우수) ───── */
/* 두 CDN 모두 로드 — 하나 차단돼도 다른 게 살아남도록 */
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css');
@import url('https://fonts.googleapis.com/css2?family=Pretendard:wght@400;500;600;700&family=Noto+Sans+KR:wght@400;500;600;700&display=swap');

html, body, .stApp {{
    font-family: 'Pretendard Variable', 'Pretendard', 'Noto Sans KR',
        -apple-system, BlinkMacSystemFont, 'Malgun Gothic', '맑은 고딕',
        'Apple SD Gothic Neo', sans-serif;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    text-rendering: optimizeLegibility;
}}

/* Material Symbols/Icons 아이콘 보호 (위 폰트가 덮어쓰지 않도록) */
[class*="material-symbols"],
[class*="material-icons"],
[class*="MuiIcon"],
.icon,
i[class*="icon"] {{
    font-family: 'Material Symbols Outlined', 'Material Icons',
        'Material Symbols Rounded', sans-serif !important;
}}

/* ───── 기본 배경/텍스트 ───── */
.stApp {{
    background-color: {COLOR_BG};
    color: {COLOR_TEXT};
}}

/* 메인 컨텐츠 좌우 패딩 살짝 여유 */
.main .block-container {{
    padding-top: 2rem;
    padding-bottom: 3rem;
    max-width: 1400px;
}}

/* 제목/본문 기본 색상을 더 진하게 */
h1, h2, h3, h4, h5, h6 {{
    color: {COLOR_TEXT} !important;
    letter-spacing: -0.01em;
}}
p, span, label, div {{
    color: {COLOR_TEXT};
}}
.stCaption, [data-testid="stCaptionContainer"] {{
    color: {COLOR_MUTED} !important;
}}

/* ───── 사이드바 ───── */
section[data-testid="stSidebar"] {{
    background-color: {COLOR_CARD};
    border-right: 1px solid {COLOR_BORDER};
}}
section[data-testid="stSidebar"] .block-container {{
    padding-top: 1.5rem;
}}
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {{
    font-size: 0.95rem;
    font-weight: 600;
    color: {COLOR_TEXT} !important;
    margin-bottom: 0.5rem;
}}
section[data-testid="stSidebar"] label {{
    color: {COLOR_MUTED} !important;
    font-size: 0.82rem;
    font-weight: 500;
}}
section[data-testid="stSidebar"] hr {{
    border-color: {COLOR_BORDER};
    margin: 1rem 0;
}}

/* ───── 사이드바 자산군 선택 (pills) ───── */
section[data-testid="stSidebar"] [data-testid="stPills"] button {{
    border-radius: 8px !important;
    border: 1px solid {COLOR_BORDER} !important;
    background: {COLOR_CARD} !important;
    color: {COLOR_MUTED} !important;
    font-weight: 500 !important;
    transition: all 0.15s ease;
}}
section[data-testid="stSidebar"] [data-testid="stPills"] button:hover {{
    background: {COLOR_HOVER} !important;
    color: {COLOR_TEXT} !important;
}}
section[data-testid="stSidebar"] [data-testid="stPills"] button[aria-pressed="true"] {{
    background: {COLOR_ACCENT} !important;
    border-color: {COLOR_ACCENT} !important;
    color: #ffffff !important;
}}

/* ───── 카드/메트릭 ───── */
div[data-testid="stMetric"] {{
    background-color: {COLOR_CARD};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
    padding: 14px 18px;
    box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
}}
div[data-testid="stMetricLabel"] {{
    color: {COLOR_MUTED} !important;
    font-size: 0.82rem;
    font-weight: 500;
}}
div[data-testid="stMetricValue"] {{
    color: {COLOR_TEXT} !important;
    font-weight: 700;
}}

/* ───── 버튼 ───── */
.stButton > button {{
    background-color: {COLOR_CARD};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    font-weight: 500;
    transition: all 0.15s ease-in-out;
    box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
}}
.stButton > button:hover {{
    border-color: {COLOR_ACCENT};
    color: {COLOR_ACCENT};
    background-color: #fff5f5;
}}
.stButton > button:active {{
    background-color: #ffe8e8;
}}

/* ───── 데이터프레임 (랭킹 테이블) ───── */
div[data-testid="stDataFrame"] {{
    background-color: {COLOR_CARD};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
    overflow: hidden;
    box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
}}
div[data-testid="stDataFrame"] [data-testid="stDataFrameResizable"] {{
    background-color: {COLOR_CARD};
}}

/* ───── 입력 컨트롤 (selectbox/text/number) ───── */
.stSelectbox [data-baseweb="select"] > div {{
    background-color: {COLOR_CARD} !important;
    border: 1px solid {COLOR_BORDER} !important;
    border-radius: 8px !important;
    color: {COLOR_TEXT} !important;
}}
.stTextInput input,
.stNumberInput input {{
    background-color: {COLOR_CARD} !important;
    color: {COLOR_TEXT} !important;
    border: 1px solid {COLOR_BORDER} !important;
    border-radius: 8px !important;
}}
.stNumberInput button {{
    background-color: {COLOR_CARD} !important;
    border: 1px solid {COLOR_BORDER} !important;
    color: {COLOR_TEXT} !important;
}}

/* ───── 슬라이더 ───── */
.stSlider [data-baseweb="slider"] [role="slider"] {{
    background-color: {COLOR_ACCENT} !important;
    border-color: {COLOR_ACCENT} !important;
}}
.stSlider [data-baseweb="slider"] > div > div > div {{
    background-color: {COLOR_ACCENT} !important;
}}

/* ───── 체크박스 ───── */
.stCheckbox label {{
    color: {COLOR_TEXT} !important;
}}

/* ───── 익스팬더 ───── */
.streamlit-expanderHeader,
[data-testid="stExpander"] summary {{
    background-color: {COLOR_CARD};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    color: {COLOR_TEXT} !important;
    font-weight: 500;
}}
[data-testid="stExpander"] [data-testid="stExpanderDetails"] {{
    background-color: {COLOR_CARD};
    border: 1px solid {COLOR_BORDER};
    border-top: none;
    border-radius: 0 0 8px 8px;
}}

/* ───── 알림 박스 (info/warning) ───── */
[data-testid="stAlert"] {{
    border-radius: 10px;
    border: 1px solid {COLOR_BORDER};
    background-color: {COLOR_CARD};
}}

/* ───── 구분선 ───── */
hr {{
    border-color: {COLOR_BORDER};
}}
</style>
"""


def apply_theme() -> None:
    """스크리닝 앱 라이트 테마 CSS를 Streamlit 페이지에 주입."""
    st.markdown(_CSS, unsafe_allow_html=True)
