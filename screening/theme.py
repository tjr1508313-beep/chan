"""스크리닝 앱 테마/스타일 (Toss-style 폴리쉬 통합본).

이 파일을 `screening/theme.py` 에 그대로 덮어쓰세요.
기존 `apply_theme()` / `COLOR_*` 상수 인터페이스 100% 호환.

포함된 토스 스타일 요소:
    - 라이트 톤 살짝 그레이쉬 (#f2f4f6)
    - 카드 radius 16~20px + 부드러운 2단 그림자
    - 액센트 = 토스 블루 #3182f6
    - 수익↑빨강 / 손실↓파랑 (한국식, 유지)
    - 별표 ★ 컬럼 (Step 2 패치 호환)
    - 미니 스파크라인 컬럼 (Step 3 패치 호환)
    - JetBrains Mono 숫자 + Pretendard 본문
"""

import streamlit as st
import streamlit.components.v1 as components

# ─── 기존 호환 상수 ──────────────────────────────────────
COLOR_BG = "#f2f4f6"
COLOR_CARD = "#ffffff"
COLOR_PROFIT = "#ff4b4b"
COLOR_LOSS = "#3182f6"
COLOR_TEXT = "#191f28"
COLOR_MUTED = "#8b95a1"
COLOR_BORDER = "#e8eaed"
COLOR_HOVER = "#f9fafb"
COLOR_ACCENT = "#3182f6"

# ─── 신규 토큰 (필요 시 ui.py 에서 import) ────────────────
COLOR_SUB = "#4e5968"
COLOR_BORDER_SOFT = "#f1f3f5"
COLOR_SURFACE2 = "#f9fafb"
COLOR_PROFIT_SOFT = "#fff0f0"
COLOR_LOSS_SOFT = "#eff6ff"
COLOR_GOLD = "#f59e0b"


_CSS = f"""
<style>
/* ───── 폰트 ───── */
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css');
@import url('https://fonts.googleapis.com/css2?family=Pretendard:wght@400;500;600;700&family=Noto+Sans+KR:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

html, body, .stApp {{
    font-family: 'Pretendard Variable', 'Pretendard', 'Noto Sans KR',
        -apple-system, BlinkMacSystemFont, 'Malgun Gothic', '맑은 고딕',
        'Apple SD Gothic Neo', sans-serif;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    text-rendering: optimizeLegibility;
    letter-spacing: -0.01em;
}}

[class*="material-symbols"], [class*="material-icons"], [class*="MuiIcon"],
.icon, i[class*="icon"] {{
    font-family: 'Material Symbols Outlined', 'Material Icons',
        'Material Symbols Rounded', sans-serif !important;
}}

.mono, .num {{ font-variant-numeric: tabular-nums; }}
.mono {{ font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, monospace; }}

/* ───── 배경/텍스트 ───── */
.stApp {{ background-color: {COLOR_BG}; color: {COLOR_TEXT}; }}
.main .block-container {{ padding-top: 0.5rem; padding-bottom: 3rem; max-width: 1480px; }}
h1, h2, h3, h4, h5, h6 {{ color: {COLOR_TEXT} !important; letter-spacing: -0.02em; font-weight: 800; }}
p, span, label, div {{ color: {COLOR_TEXT}; }}
.stCaption, [data-testid="stCaptionContainer"] {{ color: {COLOR_MUTED} !important; }}

/* ───── 사이드바 ───── */
section[data-testid="stSidebar"] {{
    background-color: {COLOR_CARD};
    border-right: 1px solid {COLOR_BORDER_SOFT};
    box-shadow: 1px 0 2px rgba(16,24,40,.02);
}}
section[data-testid="stSidebar"] .block-container {{
    padding-top: 1.5rem; padding-left: 1.25rem; padding-right: 1.25rem;
}}
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] h4,
section[data-testid="stSidebar"] h5 {{
    font-size: 0.95rem; font-weight: 800; color: {COLOR_TEXT} !important;
    margin-bottom: 0.5rem; letter-spacing: -0.01em;
}}
section[data-testid="stSidebar"] label {{
    color: {COLOR_SUB} !important; font-size: 0.78rem; font-weight: 600;
}}
section[data-testid="stSidebar"] hr {{
    border: none; border-top: 1px solid {COLOR_BORDER_SOFT}; margin: 1.25rem 0;
}}
section[data-testid="stSidebar"] [data-testid="stPills"] button {{
    border-radius: 10px !important; border: 1px solid {COLOR_BORDER} !important;
    background: {COLOR_CARD} !important; color: {COLOR_SUB} !important;
    font-weight: 600 !important; transition: all 0.15s ease;
}}
section[data-testid="stSidebar"] [data-testid="stPills"] button:hover {{
    background: {COLOR_HOVER} !important; color: {COLOR_TEXT} !important;
}}
section[data-testid="stSidebar"] [data-testid="stPills"] button[aria-pressed="true"] {{
    background: {COLOR_ACCENT} !important; border-color: {COLOR_ACCENT} !important;
    color: #ffffff !important;
}}

/* ───── 카드 / 메트릭 ───── */
div[data-testid="stMetric"] {{
    background-color: {COLOR_CARD};
    border: 1px solid {COLOR_BORDER_SOFT};
    border-radius: 16px; padding: 16px 20px;
    box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04),
                0 2px 8px rgba(16, 24, 40, 0.04);
}}
div[data-testid="stMetricLabel"] {{
    color: {COLOR_MUTED} !important; font-size: 0.78rem; font-weight: 600;
}}
div[data-testid="stMetricValue"] {{
    color: {COLOR_TEXT} !important; font-weight: 800;
    font-variant-numeric: tabular-nums;
}}

/* ───── 버튼 ───── */
.stButton > button {{
    background-color: {COLOR_CARD}; color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER}; border-radius: 12px;
    font-weight: 600; padding: 9px 16px;
    transition: all 0.15s ease-in-out;
    box-shadow: 0 1px 2px rgba(16, 24, 40, 0.03);
}}
.stButton > button:hover {{
    border-color: {COLOR_ACCENT}; color: {COLOR_ACCENT};
    background-color: {COLOR_LOSS_SOFT};
}}
.stButton > button:active {{ background-color: #dbeafe; }}

/* ───── 입력 컨트롤 ───── */
.stSelectbox [data-baseweb="select"] > div {{
    background-color: {COLOR_CARD} !important;
    border: 1px solid {COLOR_BORDER} !important;
    border-radius: 10px !important; color: {COLOR_TEXT} !important;
    min-height: 40px;
}}
.stTextInput input, .stNumberInput input {{
    background-color: {COLOR_CARD} !important; color: {COLOR_TEXT} !important;
    border: 1px solid {COLOR_BORDER} !important; border-radius: 10px !important;
    font-family: 'JetBrains Mono', ui-monospace, monospace !important;
    font-weight: 600 !important;
}}
.stNumberInput button {{
    background-color: {COLOR_HOVER} !important;
    border: 1px solid {COLOR_BORDER} !important; color: {COLOR_SUB} !important;
}}

/* ───── 슬라이더 ───── */
.stSlider [data-baseweb="slider"] [role="slider"] {{
    background-color: #ffffff !important;
    border: 2px solid {COLOR_ACCENT} !important;
    box-shadow: 0 1px 3px rgba(0,0,0,.12) !important;
}}
.stSlider [data-baseweb="slider"] > div > div > div {{ background-color: {COLOR_ACCENT} !important; }}
.stSlider [data-testid="stTickBar"] {{ color: {COLOR_MUTED} !important; font-size: 0.7rem; }}

/* ───── 체크박스/토글 ───── */
.stCheckbox label {{ color: {COLOR_TEXT} !important; font-size: 0.85rem; }}
.stCheckbox [data-testid="stMarkdownContainer"] p {{ font-size: 0.85rem !important; }}
.stToggle [data-baseweb="checkbox"] [role="checkbox"][aria-checked="true"] {{
    background-color: {COLOR_ACCENT} !important;
}}

/* ───── 익스팬더 ───── */
[data-testid="stExpander"] {{
    border: 1px solid {COLOR_BORDER_SOFT}; border-radius: 14px !important;
    overflow: hidden; background: {COLOR_CARD};
    box-shadow: 0 1px 2px rgba(16,24,40,.03);
}}
[data-testid="stExpander"] summary {{
    background-color: {COLOR_CARD}; color: {COLOR_TEXT} !important;
    font-weight: 700 !important; padding: 12px 16px !important;
}}
[data-testid="stExpander"] summary:hover {{ background: {COLOR_SURFACE2}; }}
[data-testid="stExpander"] [data-testid="stExpanderDetails"] {{
    background-color: {COLOR_SURFACE2};
    border-top: 1px solid {COLOR_BORDER_SOFT};
    padding: 12px 16px;
}}

/* ───── 알림 박스 ───── */
[data-testid="stAlert"] {{
    border-radius: 14px; border: 1px solid {COLOR_BORDER_SOFT};
    background-color: {COLOR_CARD}; padding: 14px 18px;
    box-shadow: 0 1px 2px rgba(16,24,40,.03);
}}

hr {{ border: none; border-top: 1px solid {COLOR_BORDER_SOFT}; margin: 1.5rem 0; }}

/* ───── 커스텀 랭킹 테이블 ───── */
div.st-key-scr_rank_table_us,
div.st-key-scr_rank_table_kr {{
    background-color: {COLOR_CARD};
    border: 1px solid {COLOR_BORDER_SOFT};
    border-radius: 16px;
    box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04),
                0 2px 8px rgba(16, 24, 40, 0.03);
    padding: 0; overflow: hidden;
    margin-bottom: 0.75rem;
}}

.scr-rank-header {{
    font-weight: 700; color: {COLOR_MUTED};
    font-size: 0.74rem; padding: 14px 10px 10px;
    border-bottom: 1px solid {COLOR_BORDER};
    background: {COLOR_SURFACE2};
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    letter-spacing: 0.02em; text-transform: uppercase;
}}

div.st-key-scr_rank_table_us .stButton > button,
div.st-key-scr_rank_table_kr .stButton > button {{
    background: transparent !important;
    border: none !important;
    border-bottom: 1px solid {COLOR_BORDER_SOFT} !important;
    border-radius: 0 !important; box-shadow: none !important;
    padding: 12px 10px !important;
    color: {COLOR_TEXT} !important;
    font-weight: 500 !important; font-size: 0.95rem !important;
    min-height: 44px !important;
    width: 100%; line-height: 1.3;
    justify-content: flex-end !important;
    font-variant-numeric: tabular-nums;
    transition: background-color .12s ease, color .12s ease;
}}
div.st-key-scr_rank_table_us .stButton > button:hover,
div.st-key-scr_rank_table_kr .stButton > button:hover {{
    background: {COLOR_LOSS_SOFT} !important; color: {COLOR_TEXT} !important;
}}
div.st-key-scr_rank_table_us .stButton > button:focus,
div.st-key-scr_rank_table_kr .stButton > button:focus,
div.st-key-scr_rank_table_us .stButton > button:active,
div.st-key-scr_rank_table_kr .stButton > button:active {{
    background: {COLOR_LOSS_SOFT} !important;
    outline: none !important; box-shadow: none !important;
}}

div.st-key-scr_rank_table_us .stButton > button > div,
div.st-key-scr_rank_table_kr .stButton > button > div,
div.st-key-scr_rank_table_us .stButton > button p,
div.st-key-scr_rank_table_kr .stButton > button p {{
    width: 100%; text-align: inherit !important; margin: 0 !important;
}}

/* 첫 컬럼(★) = 중앙정렬 + 골드 */
div.st-key-scr_rank_table_us [data-testid="stHorizontalBlock"] > div:first-child .stButton > button,
div.st-key-scr_rank_table_kr [data-testid="stHorizontalBlock"] > div:first-child .stButton > button {{
    color: #d1d6db !important;
    font-size: 18px !important; font-weight: 700 !important;
    padding: 8px 4px !important;
    justify-content: center !important;
    min-height: 40px !important;
    background: transparent !important;
    transition: color .12s ease, transform .15s cubic-bezier(.34,1.56,.64,1);
}}
div.st-key-scr_rank_table_us [data-testid="stHorizontalBlock"] > div:first-child .stButton > button:hover,
div.st-key-scr_rank_table_kr [data-testid="stHorizontalBlock"] > div:first-child .stButton > button:hover {{
    color: {COLOR_GOLD} !important; background: transparent !important;
    transform: scale(1.18);
}}

/* 3·4번째 컬럼(코드/종목명) = 좌측 정렬 */
div.st-key-scr_rank_table_us [data-testid="stHorizontalBlock"] > div:nth-child(3) .stButton > button,
div.st-key-scr_rank_table_us [data-testid="stHorizontalBlock"] > div:nth-child(4) .stButton > button,
div.st-key-scr_rank_table_kr [data-testid="stHorizontalBlock"] > div:nth-child(3) .stButton > button,
div.st-key-scr_rank_table_kr [data-testid="stHorizontalBlock"] > div:nth-child(4) .stButton > button {{
    justify-content: flex-start !important; text-align: left !important;
}}

/* 행 단위 hover */
div.st-key-scr_rank_table_us [data-testid="stHorizontalBlock"]:hover .stButton > button,
div.st-key-scr_rank_table_kr [data-testid="stHorizontalBlock"]:hover .stButton > button {{
    background: {COLOR_LOSS_SOFT} !important;
}}

/* 스파크라인 컬럼 */
.scr-rank-spark {{
    display: flex; align-items: center; justify-content: center;
    height: 44px; padding: 4px;
    border-bottom: 1px solid {COLOR_BORDER_SOFT};
    transition: opacity .15s ease;
}}
.scr-rank-spark svg {{ opacity: 0.85; }}
div.st-key-scr_rank_table_us [data-testid="stHorizontalBlock"]:hover .scr-rank-spark svg,
div.st-key-scr_rank_table_kr [data-testid="stHorizontalBlock"]:hover .scr-rank-spark svg {{
    opacity: 1;
}}

/* 선택 행 바로 아래에 펼쳐지는 종목 차트 */
div[class*="st-key-scr_inline_chart_"] {{
    background: {COLOR_CARD};
    border-top: 2px solid {COLOR_ACCENT};
    border-bottom: 1px solid {COLOR_BORDER};
    padding: 14px 12px 12px;
    margin: -1px 0 8px;
    box-shadow: inset 0 6px 12px rgba(49, 130, 246, 0.04);
}}

/* 프로그레스 바 */
.stProgress > div > div > div {{
    background: linear-gradient(90deg, {COLOR_ACCENT}, #60a5fa) !important;
    border-radius: 999px;
}}
.stProgress > div > div {{ background: {COLOR_BORDER_SOFT}; border-radius: 999px; }}

[data-testid="stHorizontalBlock"] {{ gap: 0.5rem; }}
</style>
"""


_NOTRANSLATE_JS = """
<script>
(function() {
    try {
        var p = window.parent.document;
        p.documentElement.setAttribute('translate', 'no');
        p.documentElement.classList.add('notranslate');
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


_SECTOR_CSS = """
<style>
.scr-sec-ribbon{display:flex;gap:5px;margin:2px 0 14px;height:62px;}
.scr-sec-tile{border-radius:4px;padding:9px 10px;display:flex;flex-direction:column;
  justify-content:space-between;min-width:0;overflow:hidden;}
.scr-sec-tile .nm{font-size:12px;font-weight:500;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;}
.scr-sec-tile .vl{font-size:13px;font-weight:500;}
.scr-sec-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:14px;
  font-family:Pretendard,-apple-system,'Malgun Gothic',sans-serif;}
.scr-sec-metric{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px 18px;}
.scr-sec-metric .lb{font-size:13px;color:#6b7280;font-weight:600;letter-spacing:-0.2px;}
.scr-sec-metric .vl{font-size:28px;font-weight:800;margin-top:3px;letter-spacing:-0.5px;}
.scr-sec-metric .vs{font-size:19px;font-weight:700;margin-top:6px;letter-spacing:-0.3px;}
.scr-sec-card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;display:flex;
  align-items:center;gap:12px;padding:12px 15px;border-left-width:4px;border-left-style:solid;}
.scr-sec-card .chip{width:28px;height:28px;border-radius:8px;font-size:14px;font-weight:500;
  display:flex;align-items:center;justify-content:center;flex:0 0 auto;}
.scr-sec-card .meta{flex:1;min-width:0;}
.scr-sec-card .meta .nm{font-size:15px;font-weight:500;}
.scr-sec-card .meta .sub{font-size:11px;color:#6b7280;margin-top:1px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.scr-sec-bar{width:54px;height:6px;border-radius:3px;background:#eef0f2;overflow:hidden;flex:0 0 auto;}
.scr-sec-bar > i{display:block;height:100%;}
.scr-sec-brd{font-size:11px;color:#9ca3af;white-space:nowrap;}
.scr-sec-pill{font-size:15px;font-weight:500;border-radius:8px;padding:5px 12px;
  min-width:64px;text-align:center;flex:0 0 auto;}
.scr-sec-mhdr{display:flex;font-size:11px;color:#9ca3af;padding:6px 4px 4px;}
.scr-sec-detail-h{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  padding:10px 4px 2px;margin-top:2px;border-top:1px solid #eef0f2;
  font-family:Pretendard,-apple-system,'Malgun Gothic',sans-serif;}
.scr-sec-detail-h .nm{font-size:19px;font-weight:800;letter-spacing:-0.3px;}
.scr-sec-detail-h .sub{font-size:12px;color:#6b7280;}
</style>
"""


_BETTING_CSS = """
<style>
/* ── 탭 버튼 (한국주식 / 미국주식) ───────────────────────────── */
div[class*="st-key-scr_tab_btn_"] > .stButton > button {
    border-radius: 8px;
    font-weight: 700;
    font-size: 0.95rem;
    padding: 8px 18px;
    transition: all 0.12s ease;
}
/* inactive (secondary) — 배경 흰색, 텍스트 회색, 테두리 연하게 */
div[class*="st-key-scr_tab_btn_"] > .stButton > button[kind="secondary"] {
    background: #ffffff !important;
    color: #6b7280 !important;
    border: 1px solid #e5e7eb !important;
    box-shadow: none !important;
}
div[class*="st-key-scr_tab_btn_"] > .stButton > button[kind="secondary"]:hover {
    color: #1a1a1a !important;
    border-color: #d1d5db !important;
    background: #f9fafb !important;
}
/* active (primary) — primaryColor(#ff4b4b) 빨강, 하단 강조선 */
div[class*="st-key-scr_tab_btn_"] > .stButton > button[kind="primaryFormSubmit"],
div[class*="st-key-scr_tab_btn_"] > .stButton > button[kind="primary"] {
    border-bottom: 3px solid #ff4b4b !important;
    border-radius: 8px 8px 4px 4px !important;
    box-shadow: 0 2px 8px rgba(255,75,75,0.15) !important;
}

/* ── 베팅 밴드 ─ × 제거 버튼 ─────────────────────────────────── */
div[class*="st-key-scr_bet_rm_"] > .stButton > button {
    background: #fff0f0 !important;
    color: #ff4b4b !important;
    border: 1px solid #fecaca !important;
    border-radius: 6px !important;
    font-size: 0.85rem !important;
    font-weight: 700 !important;
    padding: 3px 10px !important;
    min-height: 28px !important;
    box-shadow: none !important;
    line-height: 1;
}
div[class*="st-key-scr_bet_rm_"] > .stButton > button:hover {
    background: #fee2e2 !important;
    border-color: #f87171 !important;
}

/* ── 베팅 밴드 ─ 종목 카드 컬럼 경계 ───────────────────────────── */
/* 밴드 종목 영역: 섹션 라벨 아래 컨텐츠를 약한 카드처럼 묶음 */
.scr-bet-band-card {
    background: #ffffff;
    border: 0.5px solid #e5e7eb;
    border-radius: 10px;
    padding: 10px 12px;
    min-height: 72px;
}

/* ── 베팅 합계 칸 강조 ────────────────────────────────────────── */
.scr-bet-total-card {
    background: #f7f8fa;
    border: 1px solid #e5e7eb;
    border-left: 3px solid #ff4b4b;
    border-radius: 10px;
    padding: 10px 12px;
    min-height: 72px;
}
</style>
"""


def apply_theme() -> None:
    """스크리닝 앱 Toss-style 라이트 테마 CSS 주입.

    Chrome 자동 번역 차단(notranslate) 포함.
    """
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(_SECTOR_CSS, unsafe_allow_html=True)
    st.markdown(_BETTING_CSS, unsafe_allow_html=True)
    components.html(_NOTRANSLATE_JS, height=0)
