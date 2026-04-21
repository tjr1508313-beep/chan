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

## Phase 2: 한국주식 확장 (초안)
- 코스피/코스닥 대비 RS
- pykrx 또는 FDR (`StockListing('KRX')`)로 종목 리스트 확보
- 거래대금은 원화 원본 사용 가능
- 관리종목/투자주의 → KRX 공시 기반 필터
- 에이전트 신설: `한국주식 데이터 API`
- 기존 백엔드/프론트는 공통 로직 그대로 활용

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
- [x] **거래대금 기준**: **$20M 이상** (달러 고정 기준)
  - 한국주식 Phase 2에서는 원화 300억 원 기준 적용
- [x] **한글 종목명**: MVP는 영문명만, Phase 1 최종 단계에서 Top 200 수동 CSV 매핑
- [x] **데이터 캐시**: SQLite (`screening_cache.db`)
- [x] **데이터 소스**: yfinance(시세/지수/메타) + FinanceDataReader(종목 리스트)

## 미결정 (추후 확장 시 논의)
- [ ] 장중 실시간 조회 지원 여부 (MVP에선 장 마감 후 배치만)
