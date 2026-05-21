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
import streamlit.components.v1 as components

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

/* ───── 커스텀 랭킹 테이블 (행 어디든 클릭 가능) ───── */
div.st-key-scr_rank_table_us,
div.st-key-scr_rank_table_kr {{
    background-color: {COLOR_CARD};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
    box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
    padding: 2px 6px 6px;
    margin-bottom: 0.5rem;
}}

/* 헤더 셀 — markdown 으로 그림 */
.scr-rank-header {{
    font-weight: 600;
    color: {COLOR_MUTED};
    font-size: 0.82rem;
    padding: 10px 8px 6px;
    border-bottom: 1px solid {COLOR_BORDER};
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}

/* 정렬 헤더 버튼 (RS / RS가중 클릭 정렬) */
div.st-key-scr_rank_header_us .stButton > button,
div.st-key-scr_rank_header_kr .stButton > button {{
    background: transparent !important;
    border: none !important;
    border-bottom: 1px solid {COLOR_BORDER} !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    padding: 10px 8px 6px !important;
    color: {COLOR_MUTED} !important;
    font-weight: 600 !important;
    font-size: 0.82rem !important;
    min-height: unset !important;
    width: 100%;
    white-space: nowrap;
    justify-content: flex-end !important;
}}
div.st-key-scr_rank_header_us .stButton > button:hover,
div.st-key-scr_rank_header_kr .stButton > button:hover {{
    color: {COLOR_TEXT} !important;
    background: transparent !important;
}}
div.st-key-scr_rank_header_us .stButton > button > div,
div.st-key-scr_rank_header_kr .stButton > button > div,
div.st-key-scr_rank_header_us .stButton > button p,
div.st-key-scr_rank_header_kr .stButton > button p {{
    justify-content: flex-end !important;
    text-align: right !important;
    width: 100%;
}}

/* 데이터 셀 = 투명 버튼 (행 어디든 클릭하면 차트 열림) */
div.st-key-scr_rank_table_us .stButton > button,
div.st-key-scr_rank_table_kr .stButton > button {{
    background: transparent !important;
    border: none !important;
    border-bottom: 1px solid #f3f4f6 !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    padding: 6px 8px !important;
    color: {COLOR_TEXT} !important;
    font-weight: 400 !important;
    font-size: 0.92rem !important;
    min-height: 34px !important;
    width: 100%;
    line-height: 1.25;
    justify-content: flex-end !important;
}}
div.st-key-scr_rank_table_us .stButton > button:hover,
div.st-key-scr_rank_table_kr .stButton > button:hover {{
    background: #fff5f5 !important;
    color: {COLOR_ACCENT} !important;
}}
div.st-key-scr_rank_table_us .stButton > button:focus,
div.st-key-scr_rank_table_kr .stButton > button:focus,
div.st-key-scr_rank_table_us .stButton > button:active,
div.st-key-scr_rank_table_kr .stButton > button:active {{
    background: #fff5f5 !important;
    color: {COLOR_ACCENT} !important;
    outline: none !important;
    box-shadow: none !important;
}}
/* 텍스트(span) 도 정렬을 따르게 */
div.st-key-scr_rank_table_us .stButton > button > div,
div.st-key-scr_rank_table_kr .stButton > button > div,
div.st-key-scr_rank_table_us .stButton > button p,
div.st-key-scr_rank_table_kr .stButton > button p {{
    width: 100%;
    text-align: inherit !important;
}}

/* 2·3번째 컬럼(코드/종목명)은 좌측 정렬, 나머지는 우측 정렬(위의 기본값) */
div.st-key-scr_rank_table_us [data-testid="stHorizontalBlock"] > div:nth-child(2) .stButton > button,
div.st-key-scr_rank_table_us [data-testid="stHorizontalBlock"] > div:nth-child(3) .stButton > button,
div.st-key-scr_rank_table_kr [data-testid="stHorizontalBlock"] > div:nth-child(2) .stButton > button,
div.st-key-scr_rank_table_kr [data-testid="stHorizontalBlock"] > div:nth-child(3) .stButton > button {{
    justify-content: flex-start !important;
    text-align: left !important;
}}

/* 행 단위 hover — 같은 행의 버튼들이 동시에 회색배경 (가능하면) */
div.st-key-scr_rank_table_us [data-testid="stHorizontalBlock"]:hover .stButton > button,
div.st-key-scr_rank_table_kr [data-testid="stHorizontalBlock"]:hover .stButton > button {{
    background: #fff5f5 !important;
}}
</style>
"""


_NOTRANSLATE_JS = """
<script>
(function() {
    try {
        var p = window.parent.document;
        // documentElement (=<html>) 에 translate=no + class notranslate
        p.documentElement.setAttribute('translate', 'no');
        p.documentElement.classList.add('notranslate');
        // <head> 에 google notranslate meta 1회만 주입
        if (!p.querySelector('meta[name="google"][content="notranslate"]')) {
            var m = p.createElement('meta');
            m.name = 'google';
            m.content = 'notranslate';
            (p.head || p.documentElement).appendChild(m);
        }
    } catch (e) { /* 무시 */ }
})();
</script>
"""


def apply_theme() -> None:
    """스크리닝 앱 라이트 테마 CSS를 Streamlit 페이지에 주입.

    Chrome 자동 번역이 미국 티커/종목명(MRAM→엠람, FLEX→몸을 풀다 등)을
    멋대로 한국어로 바꾸는 문제 차단 → notranslate meta + translate=no 속성 추가.
    한국 종목명(한국어→한국어)에는 영향 없음.
    """
    st.markdown(_CSS, unsafe_allow_html=True)
    components.html(_NOTRANSLATE_JS, height=0)
