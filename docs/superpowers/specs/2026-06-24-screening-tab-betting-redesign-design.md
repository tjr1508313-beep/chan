# 스크리닝 화면 — 탭 네비게이션 + ㄴ자 베팅 계산기 재설계

작성일: 2026-06-24
대상: `screening/ui.py`(주), `screening/theme.py`, `screening.py`(진입점) / 베팅 로직 재사용

## 1. 배경 / 목표

현재 화면은 미국주식·한국주식을 **좌우 2열로 동시 표시**하고, 베팅 계산기는 **좌측 사이드바**에 있다.
문제: ① 좌우 분할로 각 시장이 좁고 ② 상단 여백 낭비 ③ 사이드바·베팅이 본문과 분리되어
종목을 고른 뒤 베팅 계산을 바로 보기 불편하다.

목표:
- 한국주식 / 미국주식을 **탭으로 분리**(기본 한국, 버튼으로 미국 전환). 활성 시장만 렌더.
- 한 시장이 화면을 넓게 쓰되, 베팅 계산기는 **'ㄴ'자**로 압축 배치해 공간 낭비 제거.
- 종목을 "담기" 하면 같은 화면에서 즉시 베팅 계산(화면 이동 없음).
- 좌측 사이드바 제거(빈 채로 접힘, 좌상단 토글 화살표만 유지).

## 2. 현재 상태 (요약)

- 진입점 `screening.py` → `main()` → `render_screening_page()`(`screening/ui.py:2615`).
- `render_screening_page()`: 사이드바(`_render_betting_calculator_and_basket_sidebar` + 시장별 `_render_sidebar`),
  본문 `st.columns(2)`로 US/KR 카드+차트+`_render_screening_section`.
- `_render_screening_section` → `_render_rs_header`(지수/기간/표시 컨트롤) + 보기방식 라디오(섹터별/전체 RS) + 섹터뷰/랭킹표.
- 베팅: `_render_betting_calculator_and_basket_sidebar`(`ui.py:2241`)가 `scr_basket`(종목 바구니)을 사용.
  - 자산(만원)·리스크%·손절N배·환율 입력, `total_risk = 자산×리스크%`, `per_risk = total_risk // 바구니수`.
  - 종목별: `stop_dist = atr9 × N`, `shares = floor(per_risk / stop_dist)`, `stop_price = price − stop_dist`. US는 환율 환산.
  - 바구니 item = `{ticker, name, spec_code, price, atr9}`. 차트의 "바구니에 담기" 버튼으로 추가.
- Streamlit 1.58 (st.navigation 등 가능하나 본 설계는 미사용 — 4.1 참고).

## 3. 이미 적용된 별개 변경 (맥락 — 본 spec 범위 아님)

같은 작업 세션에서 먼저 적용·테스트 완료(미커밋):
- 섹터 느슨 필터: KR 거래대금 100억↑·시총 3,000억↑, US $10M↑·$300M↑ (`sector.py`).
- `exclude_caution` 옵션 신설(투자경고·투자주의·단기과열 등 배지 종목 제외) → 섹터 필터에 적용(`core.py`).
- 상단 "오늘의 시장" 헤딩 제거, 카드에 기간 상세 병합, "RS Top N" 제목 제거, 상단 패딩 축소.

본 spec(탭/베팅 재설계)이 이 위에 얹힌다. UI 일부(상단 헤딩/카드)는 본 설계로 재배치된다.

## 4. 설계

### 4.1 네비게이션 — session_state 뷰 라우터 (방식 A)

- `render_screening_page()` 단일 진입점 유지(통합 대비 규칙). 내부에서 탭 라우팅.
- 상단에 탭 버튼 2개: `[한국주식]`(기본) `[미국주식]`. `st.session_state["scr_active_tab"]` ∈ {"kr","us"}.
  - 버튼 클릭 시 값 변경 후 `st.rerun()`. 활성 탭 버튼은 강조 스타일.
- **활성 시장만** `_render_market_tab(spec)` 호출 → 비활성 시장 계산/렌더 없음(성능).
- 사이드바: 렌더하지 않음. `set_page_config(initial_sidebar_state="collapsed")`로 접어둠.
  - 대안 B(`st.navigation(position="top")`)·C(`st.tabs`)는 비활성 탭도 렌더(C)하거나 페이지 분리 부담(B)이라 미채택.

### 4.2 레이아웃 — 탭 본문 (ㄴ자 베팅)

`_render_market_tab(spec)` 세로 순서:

1. **상단 행** `st.columns([1.5, 1])`:
   - 좌: 지수 카드(종가·N일 수익률·기간 상세) + 110일 미니 차트(`_render_market_card`/`_render_market_index_chart` 재사용).
   - 우: **베팅 설정 블록**(ㄴ의 세로 부분) — 자산(만원)·리스크%·손절N배·**분할 수** + 요약(총 리스크 예산, 종목당 배분).
2. **베팅 밴드**(전체 폭, ㄴ의 가로 부분): 담은 종목 칸들 + **합계 칸**.
   - 칸당: 종목명·현재가·손절가·주당 리스크·수량·투자금 + 제거(×).
   - 합계 칸: 총 투자금·총 리스크·자산 대비%·잔여 현금.
   - 담은 종목 0개면 안내 캡션만.
3. **컨트롤 줄**(전체 폭): 지수 / 기간(일) / 표시(개) + 필터 설정(expander, 한 줄) + 데이터 새로고침.
   - 보기방식 라디오(섹터별 보기 / 전체 RS 보기) + 전체 섹터 보기 토글 유지.
4. **섹터/종목**(전체 폭): 섹터 타일·종목 리스트(`_render_sector_view`) 또는 전체 RS 랭킹표.
   - 종목 클릭 → 종목 정보 + 5MA·9ATR 차트(**종목 정보만**, 베팅 숫자 없음).
   - 종목 행/차트에 **＋담기** 버튼 → 베팅 밴드에 추가.

### 4.3 베팅 계산기 (상태 · 로직 · 재사용)

- 상태: 기존 단일 저장소 `scr_basket`(= picks) 재사용. item = `{ticker, name, spec_code, price, atr9}`.
  - 탭별 표시는 `spec_code`로 필터링(활성 탭 시장의 picks만 밴드에 노출). 신규 키 없음 → prefs 마이그레이션 불필요.
  - 시장별 최대 5개(분할 수 상한과 일치).
- 전역 설정(기존 prefs 재사용): `scr_portfolio_value`(만원), `scr_risk_pct`, `scr_stop_n_mult`, `scr_fx_rate`.
- **분할 수** 신설: `scr_bet_split`(정수, 기본 3, 범위 1~5). 전역(탭 공유) 또는 시장별 — 1차는 전역.
- 계산(기존 `_render_betting_calculator_and_basket_sidebar` 로직 이전·수정):
  - `total_risk = 자산만원 × 10000 × 리스크%/100`
  - `종목당 리스크(per_risk) = total_risk ÷ 분할 수`  ← **변경점**: 기존 `// 바구니수` → 명시 분할 수.
    - 담은 수가 분할 수보다 많으면 안내(예산 초과 가능)하되 계산은 분할 수 기준 유지.
  - 종목별: `손절폭 = atr9 × N`, `손절가 = price − 손절폭`, `수량 = floor(per_risk / 손절폭)`, `투자금 = 수량 × price`.
    - US는 `atr9_krw = atr9 × fx_rate`로 환산해 per_risk(원) 대비 계산(기존 로직 유지).
  - 합계: `총 투자금 = Σ투자금`, `총 리스크 = Σ(수량 × 손절폭)`, `자산 대비% = 총투자금 ÷ (자산만원×10000)`, `잔여 현금 = 자산 − 총투자금`.
- 손절가·주당 리스크는 분할 수와 무관하게 항상 확정. 분할 수 변경 시 수량·투자금·합계만 갱신.
- ATR9는 **담기 시점**에 picks에 저장(기존과 동일 — 차트 계산부에서 price+atr9 확보). 신규 백엔드 헬퍼 불필요.

### 4.4 사이드바 제거

- `_render_sidebar`의 위젯들(지수 상태 배지, 데이터 새로고침, 즐겨찾기 토글, 필터 설정 expander)을
  탭 본문 컨트롤 줄로 이전. `filter_config` 빌드는 별도 함수로 분리:
  - `_build_filter_config(spec)` — session_state에서 읽어 dict 구성(렌더와 분리).
  - `_render_filter_controls(spec)` — 컨트롤 줄/필터 expander 위젯 렌더.
- 베팅 전역 설정·환율은 베팅 설정 블록(우상단)으로 이전.
- 원격 캐시 동기화 배지(`_render_remote_sync_badge`)는 컨트롤 줄 또는 탭 상단 소형 배지로 이전.

### 4.5 모듈 / 함수 구조 (격리)

- `render_screening_page()` — prefs 로드, 탭 라우터, 활성 탭 위임.
- `_render_market_tab(spec)` — 한 시장 전체 화면(4.2). 책임: 레이아웃 조립.
- `_render_betting_panel(spec)` — 베팅 설정 블록 + 밴드 + 합계(계산 포함). 입력: picks·prefs. 출력: 렌더.
- `_compute_bet_rows(picks, settings)` — 순수 계산 함수(테스트 대상). 입력 picks+설정 → 행별·합계 결과 dict. UI 무관.
- `_render_filter_controls(spec)` / `_build_filter_config(spec)` — 컨트롤·필터(4.4).
- 기존 `_render_sector_view`/`_render_screening_section`/`_render_market_card`/`_render_market_index_chart` 재사용.

### 4.6 session_state 키 (모두 `scr_`/`scr_kr_`/`scr_us_` 접두사 유지)

- 신규: `scr_active_tab`("kr"|"us", 기본 "kr"), `scr_bet_split`(int, 기본 3).
- picks 저장소: 기존 `scr_basket` 재사용(`spec_code`로 탭별 필터).
- 재사용: `scr_portfolio_value`, `scr_risk_pct`, `scr_stop_n_mult`, `scr_fx_rate`, 시장별 `selected_index`/`rs_period`/`top_n`/`view_mode` 등.

## 5. 데이터 / 백엔드

- 신규 백엔드 불필요. ATR9·price는 담기 시점 picks에 저장(기존 차트 계산부 활용).
- `_compute_bet_rows`는 순수 함수로 분리해 단위 테스트.

## 6. 엣지 케이스

- 자산 0 / 리스크 0 → 총 리스크 0 → 수량 "—", 합계 0.
- 담은 수 > 분할 수 → 안내 문구(예산 초과 가능), 계산은 분할 수 기준.
- ATR9 결측/0 → 해당 칸 수량 "—".
- 분할 수 변경 → 즉시 갱신(rerun). picks 비었을 때 밴드 안내 캡션.
- 탭 전환 시 각 시장 picks·설정 보존.
- 미국 탭: 가격·ATR·손절가 $ 표기, per_risk 비교는 원화 환산(기존 로직).

## 7. 테스트

- `_compute_bet_rows` 단위 테스트(`tests/`): KR/US, 분할 수 변화, 자산 0, ATR 0, 합계·자산대비%·잔여현금.
- 기존 테스트(필터/섹터/UI 패널) 회귀 통과 유지.
- UI 렌더는 import/스모크 수준 점검(Streamlit 시각 검증은 사용자 확인).

## 8. 범위 밖 (Out of scope)

- 여러 종목 누적 "비교" 고급 기능, 익절 목표가(2R·3R), 분할 프리셋 버튼, 지수 RS 요약 카드(사용자가 제외).
- 매매일지 통합(추후 사용자 담당).

## 9. 통합 대비 규칙 준수

- 진입점 `render_screening_page()` 단일 유지, `set_page_config`는 `main()` 안.
- session_state 키 `scr_` 접두사, CSS는 `theme.apply_theme()`, 캐시 함수 `us_`/`screen_` 접두사.
- 배포: 작업 후 `main` push 필요(Streamlit Cloud). 임시/캐시 파일 커밋 금지.
