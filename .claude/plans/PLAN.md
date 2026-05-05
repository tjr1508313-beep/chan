# 주식 스크리닝 프로젝트 계획서

## 프로젝트 개요
상대강도(RS) 기반 주식 스크리닝 툴. 지수 대비 강한 종목 상위 20개를 자동 추출하고, 5MA + 9ATR 차트로 빠르게 검토 가능.

## 자산 확장 로드맵
1. **Phase 1 — 미국주식 MVP** (현재 진행 예정)
2. **Phase 2 — 한국주식** (나중)
3. **Phase 3 — 코인** (나중)
4. **Phase 4 — 매매일지 통합** (사용자가 직접 루트 폴더 통합)

---

## Phase 1: 미국주식 MVP (상세)

### 목표
- 나스닥 / S&P 500 각각 RS Top 20 확인
- RS 계산 기간 조정 가능 (기본 20일)
- 필터 5종 적용 (가격/거래대금/관리종목/중국기업/변동성)
- 종목 차트: 5MA + 9ATR

### 작업 순서

#### 1.1 프로젝트 스켈레톤 ✅ (2026-04-21)
- [x] `C:\스크리닝\` 루트 세팅 + git init + 초기 커밋
- [x] `.gitignore` (DB, Parquet, 시크릿, `__pycache__`)
- [x] `requirements.txt` — `>=` 최소 버전 표기
- [x] `screening/` 서브패키지 (`__init__.py`, `ui.py`, `core.py`, `data.py`, `cache.py`, `theme.py`)
- [x] `screening.py` 진입점 — `main()` 안에서 `set_page_config`, 탭 `[미국] [한국] [코인]`
- [x] `start.sh` / `스크리닝 실행.bat`

#### 1.2 데이터 API 연동 ✅ (2026-04-21)
- [x] 데이터 소스: **yfinance + FDR**
- [x] `screening/data.py`: 나스닥/S&P500 티커 리스트(`us_get_nasdaq_tickers`, `us_get_sp500_tickers`), 일봉(`us_load_prices`, `auto_adjust=True`), 지수(`us_load_index`), 메타(`us_get_meta`)
- [x] `screening/china_filter.py` + `data/china_stocks.csv` — ADR 30개 시드 + country fallback 2단계 판정
- [x] 한글명 매핑(`data/us_ticker_kr.csv`) — 1.8에서 완료

#### 1.3 캐시 계층 ✅ (2026-04-21)
- [x] `screening/cache.py`: SQLite 4테이블 (`prices`, `metadata`, `index_prices`, `settings`), CRUD + TTL
- [x] `screening/batch.py`: `screen_refresh_prices/_meta/_index` 오케스트레이션 (증분 + rate limit)
- [x] `dollar_volume` 자동 계산 저장 (Phase 1.4에서 바로 사용)

#### 1.4 필터링 로직 ✅ (2026-04-21)
- [x] `screen_build_screening_df(tickers, lookback_days=20)` — 캐시 집계
- [x] `screen_apply_filters(df, config)` — 5종 필터 순차 적용 + stats 반환 (`total → after_price → … → final`)
- [x] 변동폭 공식: `(High - Low) / prev_close`, 기본 50% 이상 제외

#### 1.5 RS 계산 로직 ✅ (2026-04-21)
- [x] 공식 확정: **단순 비율 방식** `RS = (종목 N일 수익률) / (지수 N일 수익률)`, epsilon 처리
- [x] `screen_calc_rs(prices, index_prices, period)` — 단일/wide 포맷 지원
- [x] `screen_rank_rs(tickers, index_code, period, top_n)` — 캐시 직접 조회 편의 함수
- [x] 테스트: AAPL/MSFT/NVDA/BABA + ^IXIC로 합리적 랭킹 확인 (NVDA 1위)
- 🔖 Phase 1 완료 후 블로그(best-n-optimal) 재확인하여 가중 합산으로 개선 검토

#### 1.6 UI — 랭킹 테이블 ✅ (2026-04-21)
- [x] 사이드바: 지수(나스닥/S&P) + RS 기간 슬라이더 + Top N 슬라이더 + 캐시 새로고침 + 필터 설정 expander
- [x] 메인 테이블: 순위 / 티커 / 종목명 / 현재가 / RS / N일 수익률 / 거래대금(M$) — 한국식 색상
- [x] 행 선택 → `st.session_state["scr_selected_ticker"]` 저장 → 차트 패널 연동
- [x] 필터 축소 흐름 캡션 + 지수 음수 수익률 경고 + 빈 상태 안내

#### 1.7 UI — 차트 패널 ✅ (2026-04-21)
- [x] Plotly 2행 서브플롯 (캔들 + 5MA / 9-ATR)
- [x] 5일 이평선 (SMA)
- [x] 9일 ATR (Wilder 공식)
- [x] 다크 테마 + 한국식 색상 (상승 빨강 `#ff4b4b` / 하락 파랑 `#1a9cff`), 주말 rangebreak, 하단 3칸 메트릭

#### 1.8 마감 작업 ✅ (2026-04-21)
- [x] 한글 종목명 CSV 매핑 (`data/us_ticker_kr.csv`, 시드 69종) — `us_get_meta`에서 자동 조회
- [x] 전체 파이프라인 스모크 테스트 (build → filter → rank)
- [x] `MEMORY.md` 초기 기록 (프로젝트 루트)
- [ ] 실행 테스트 (Streamlit 런타임, 사용자 몫)
- [ ] README (필요 시, 현 시점 CLAUDE.md로 충분)
- [x] Phase 1 완료 체크

### Phase 1 완료 🎉
모든 구현 체크 완료. 사용자가 `streamlit run screening.py`로 실 환경 테스트 진행 단계.

---

## Phase 2: 한국주식 확장 (착수 — 2026-04-28)

### 확정 결정 사항
- **데이터 소스**: **FDR 단일** (`StockListing`, `DataReader`)
  - pykrx 는 KRX 익명 접근 차단으로 **제외** (KRX_ID/PW 환경변수 필요해 MVP 부담)
- **지수**: KOSPI = `KS11`, KOSDAQ = `KQ11`
- **거래대금 계산**: `Close × Volume` (FDR 일봉에 Amount 컬럼 없음 — 미국과 동일 방식)
- **거래대금 필터 기준**: **300억 원 이상**
- **한글 종목명**: FDR `StockListing` 의 `Name` 컬럼이 이미 한글 — 별도 매핑 불필요
- **티커 형식**: 6자리 숫자 (예: `005930`) — 미국 영문 티커와 자연 분리, 같은 DB 테이블 공유
- **캐시 DB**: 같은 `screening_cache.db` (`prices`, `metadata`, `index_prices` 테이블 공유)

### 보류 (Phase 2 본 트랙에서 분리)
- **관리종목/투자주의 필터** — 가장 깔끔한 출처(pykrx)가 막혀 별도 KRX 공시 크롤러 필요.
  관리종목은 거래대금이 적어 300억 원 필터에서 대부분 자연 탈락. 사용자 사용 후 필요시 별도 모듈로 추가.

### 작업 순서
- [x] 2.1 의존성 — `pykrx>=1.0.45` 추가 (옵션 — KRX 인증 셋업 시 활용 가능, 미사용 시 무해). FDR 은 기존 유지.
- [x] 2.2 새 에이전트 정의 `.claude/agents/agent5-kr-data.md`
- [x] 2.3 `screening/data_kr.py` — `kr_get_kospi_tickers`, `kr_get_kosdaq_tickers`,
  `kr_load_prices`, `kr_load_index`, `kr_get_meta` (StockListing 프로세스 캐싱)
- [x] 2.4 `screening/batch_kr.py` — 미국 `batch.py` 와 대칭 별도 파일.
  `screen_refresh_prices_kr/_meta_kr/_index_kr` 제공.
- [x] 2.5 `core.py` 검증 — **수정 0줄**로 KR 데이터에서 동작 확인.
  스모크 테스트: 5 KOSPI 종목 + KS11, 20일 RS → SK하이닉스 1위 RS 1.893, 삼성전자우 2위 RS 1.270.
- [x] 2.6 `render_kr_tab()` 본격 구현 (`screening/ui.py`):
  - `_render_sidebar_kr()` (코스피/코스닥, 최소 주가/거래대금 원화, 관리종목 보류 안내)
  - `_run_refresh_kr()` (FDR 기반 새로고침 — 지수/시세/메타)
  - `_render_ranking_table_kr()` (₩ 표기 현재가, 거래대금 단위 억원)
  - `_kr_render_chart()` + `_render_chart_metrics_kr()` (₩ 표기 캔들 + 5MA + 9ATR)
  - session_state 키 분리: `scr_kr_*` (미국 사이드바와 독립)
  - `ui_load_index_tickers()` 에 KS11/KQ11 분기 추가
  - `_INDEX_DISPLAY` 에 코스피/코스닥 추가
- [x] 2.7 사용자 결정 추가 필터 (2026-04-28)
  - 모집단 정적 제외: **우선주 + 리츠 + ETF + 스팩 + 외국기업** (`data_kr._apply_universe_filter`)
    - KOSPI 949 → 812, KOSDAQ 1,821 → 1,722
  - 시가총액 ≥ **3,000억 원** (`core.py` 에 `min_market_cap` 신규 단계 + UI 슬라이더)
    - 코스피 ~425, 코스닥 ~404 종목까지 좁아짐 (3000억 기준)
  - 위험종목 제외 체크박스 노출 (UI 적용 완료, 데이터 소스는 별도 작업)
- [ ] 2.8 사용자 실행 테스트 (사이드바 → 한국주식 → 데이터 새로고침 → RS 랭킹 → 차트)
- [ ] 2.9 한국 시장 휴장일/시간대 미반영 부분 점검 (FDR 자체가 영업일만 반환하므로 큰 이슈 없을 것으로 예상)
- [ ] 2.10 (보류) 관리종목 필터 데이터 소스 확보
- [x] 2.11 RS 시간 정합성 영구 보장 (2026-05-06)
  - `core.py: screen_filter_by_index_lag(tickers, index_code, max_lag_days=0)` 신설
  - 종목 캐시 마지막일이 지수 마지막일보다 0일 초과로 뒤처지면 ranking 단계 진입 전 제외
  - `ui.py: ui_load_ranked_df` 흐름에 끼워넣어 `stats['lag_excluded']` / `stats['after_lag']` 추가
  - `_render_pipeline_badge` 에 `lag_excluded > 0` 일 때만 "지연 -N" 표시
  - **KRX 정보데이터시스템 익명 호출 차단 확인** (응답: `LOGOUT`)
  - **pykrx 1.2.7 에 admin/warning 함수 없음** 확인
  - 옵션: (a) KRX 회원 ID/PW 셋업, (b) DART API 키, (c) 네이버 스크래핑(약관 회색), (d) 보류
  - 현재는 (d) 보류 — 시가총액 3,000억 + 거래대금 300억 + 변동성 필터로 위험종목 자연 탈락 의존

### Phase 2 잔여 의사결정 (Phase 1 완료 후 검토)
- 거래대금 컬럼명 `dollar_volume` 이 한국에서 의미상 어색 — 향후 `traded_value` 등으로 일반화 검토
- 차트 함수의 미국/한국 중복은 추후 `_render_chart_panel(currency_symbol, price_format, ...)` 일반화 검토
  (현재는 `_us_render_chart` / `_kr_render_chart` 별도)

## Phase 3: 코인 확장 (초안)
- BTC 또는 시장 전체(총 시가총액) 대비 RS
- 바이낸스 / 업비트 / 빗썸 API
- 24시간 거래량 기준
- 관리종목 개념 없음 / 중국기업 필터도 해당 없음
- 변동성 필터는 기준 완화 검토 (코인은 변동성이 기본적으로 큼)
- 에이전트 신설: `코인 데이터 API`

## Phase 4: 매매일지와 통합
- 사용자가 직접 `C:\테스트\` + `C:\스크리닝\` 을 상위 폴더로 묶음
- 하나의 Streamlit 앱에서 좌측 사이드바로 [매매일지] [스크리닝] 전환
- DB 파일은 분리 유지 권장 (`trading_journal.db`, `screening_cache.db`)

---

## 확정된 MVP 결정 사항 (2026-04-21)
- [x] **RS 공식**: 단순 비율 방식 — `RS = (종목 N일 수익률) / (지수 N일 수익률)`
  - 기본 기간 20일, 사이드바 슬라이더로 5~60일 조정 가능
  - Phase 1 완료 후 블로그(best-n-optimal) 재확인 시 가중 합산으로 변경 가능
- [x] **거래대금 기준**:
  - 미국주식: **$20M 이상** (달러 고정)
  - 한국주식: **300억 원 이상** (원화 고정 — Phase 2)
- [x] **한글 종목명**: MVP는 영문명만, Phase 1 최종 단계에서 Top 200 수동 CSV 매핑
- [x] **데이터 캐시**: SQLite (`screening_cache.db`)
- [x] **데이터 소스**: yfinance(시세/지수/메타) + FinanceDataReader(종목 리스트)

## 미결정 (추후 확장 시 논의)
- [ ] 장중 실시간 조회 지원 여부 (MVP에선 장 마감 후 배치만)
