# 스크리닝 프로젝트 메모리

> RS 시간 정합성 보장 추가 직후 스냅샷 — 2026-05-06 기준.
> Phase 1 (미국주식) 완료, Phase 2.1~2.7 + 2.11 완료, 2.8(사용자 실행 테스트) 진행 중.

## 프로젝트 구조
```
C:\스크리닝\
├── screening.py              # Streamlit 진입점 (main)
├── screening/                # 로직 패키지 (통합 시 통째로 이동 대상)
│   ├── __init__.py
│   ├── ui.py                 # Streamlit UI (render_us_tab / render_kr_tab / render_crypto_tab)
│   ├── core.py               # RS 계산, 필터링 (시총 단계 추가됨), 랭킹
│   ├── cache.py              # SQLite 캐시 CRUD + 일괄 last_date 조회
│   ├── batch.py              # 미국 배치 (yfinance)
│   ├── batch_kr.py           # 한국 배치 (FDR) — 미국과 대칭 별도 파일
│   ├── data.py               # yfinance + FDR 미국 외부 API
│   ├── data_kr.py            # FDR 한국 외부 API + 모집단 정적 필터
│   ├── china_filter.py       # 중국기업 판정 (미국 한정)
│   └── theme.py              # 라이트 테마 CSS
├── data/
│   ├── china_stocks.csv      # 중국 ADR 시드 30개
│   └── us_ticker_kr.csv      # 한글명 매핑 (미국 한정, 시드 69개)
├── screening_cache.db        # SQLite 영속 캐시 (gitignored, 미국+한국 공유)
├── requirements.txt          # `>=` 최소 버전
├── .claude/agents/           # agent1~5 정의 (agent5-kr-data 추가됨)
├── .claude/plans/PLAN.md     # 단계별 작업 계획서
└── CLAUDE.md                 # 프로젝트 규칙
```

## 핵심 함수 레퍼런스

### `screening/data.py` (미국 외부 API)
- `us_get_nasdaq_tickers() -> list[str]` — FDR, 약 3,860개
- `us_get_sp500_tickers() -> list[str]` — FDR, 약 503개
- `us_load_prices(ticker, days) -> DataFrame` — yfinance, auto_adjust=True, OHLCV
- `us_load_index(index_code, days) -> DataFrame` — `^IXIC`/`^GSPC`
- `us_get_meta(ticker) -> dict` — name_en/name_kr/sector/country/exchange/market_cap/is_china/is_risk
- `us_get_kr_name(ticker) -> str | None` — CSV 매핑 조회

### `screening/data_kr.py` (한국 외부 API — FDR 단일)
- `kr_get_kospi_tickers() -> list[str]` — KOSPI, 모집단 정적 필터 적용 후 약 812개
- `kr_get_kosdaq_tickers() -> list[str]` — KOSDAQ, 약 1,722개
- `kr_load_prices(ticker, days) -> DataFrame` — FDR DataReader, OHLCV (6자리 코드)
- `kr_load_index(index_code, days) -> DataFrame` — `KS11`/`KQ11`
- `kr_get_meta(ticker) -> dict` — name_kr(한글명 자동), market_cap, country='South Korea'
- 내부: `_apply_universe_filter(df)` — 우선주(코드 끝 5 + 이름 끝 우/우A~C/2우B) / 리츠 / ETF (KODEX/TIGER 등 키워드) / 스팩 / 외국기업 (Dept 또는 ISU_CD non-KR) 정적 제거
- `_LISTING_CACHE` 프로세스 내 1회 캐시 (FDR `StockListing` 호출 절약)

### `screening/cache.py` (SQLite — 미국+한국 공유)
- DB: `screening_cache.db` (프로젝트 루트 고정)
- 테이블: `prices` (+dollar_volume 자동 — 한국에선 원화 거래대금), `metadata`, `index_prices`, `settings`
- CRUD: `cache_save_prices/load_prices/save_meta/load_meta/save_index/load_index`
- 증분 커서: `cache_get_last_price_date`, `cache_get_last_index_date`
- **신규**: `cache_get_all_last_price_dates()` — 한 SQL 로 모든 ticker 마지막일 일괄 조회 (stale-first 정렬용)
- TTL 체크: `cache_meta_age_days`

### `screening/batch.py` (미국 오케스트레이션)
- `screen_refresh_prices(tickers, days=300, force=False, sleep_sec=0.2)`
- `screen_refresh_meta(tickers, ttl_days=7, force=False, sleep_sec=0.3)`
- `screen_refresh_index(index_code, days=300, force=False)`
- 반환: `{"updated": int, "skipped": int, "failed": list[str]}`

### `screening/batch_kr.py` (한국 오케스트레이션 — FDR)
- `screen_refresh_prices_kr(tickers, days=300, force=False, sleep_sec=0.1)` — 미국보다 sleep 짧음
- `screen_refresh_meta_kr(tickers, ttl_days=7, force=False, sleep_sec=0.0)` — listing 프로세스 캐시 활용
- `screen_refresh_index_kr(index_code, days=300, force=False)` — `KS11`/`KQ11`
- 티커 정규화: `.zfill(6)` (대문자화 X)

### `screening/core.py` (로직)
- `screen_build_screening_df(tickers, lookback_days=20)` — 캐시 집계 wide DF (market_cap 컬럼 포함)
- `screen_apply_filters(df, config) -> (df, stats)` — 6종 필터, 순서: price→volume→**market_cap**→risk→china→volatility
  - `min_market_cap`: 0=미적용 / 한국 권장 3e11(3,000억 원)
- `screen_filter_by_index_lag(tickers, index_code, max_lag_days=0) -> (passing, excluded)` — RS 시간 정합성 보장. 종목 캐시 마지막일이 지수보다 N일 초과 뒤처지면 제외 (2026-05-06 추가)
- `screen_calc_rs(prices, index_prices, period=20)` — 단일/wide 지원
- `screen_rank_rs(tickers, index_code, period=20, top_n=20) -> DataFrame`

### `screening/ui.py` (UI)
- `render_asset_selector()` — 사이드바 최상단 `st.pills` (미국/한국/코인)
- `render_us_tab()` / `render_kr_tab()` / `render_crypto_tab()` — 자산군별 탭
- 한국 전용 헬퍼: `_render_sidebar_kr` / `_run_refresh_kr` / `_render_ranking_table_kr` / `_kr_render_chart`
- 공유 헬퍼: `_render_rs_header` (RS Top N 헤더 + 지수 N일 수익률), `_render_pipeline_badge` (필터 축소 흐름), `_sort_tickers_stale_first` (stale starvation 방지)

## 확정된 결정 사항

### MVP (2026-04-21)
- **RS 공식**: `(종목 N일 수익률) / (지수 N일 수익률)`, epsilon 1e-9
- **변동폭 공식**: `(High - Low) / prev_close`
- **ATR 공식**: Wilder 9일 (`ATR_t = (ATR_{t-1}*8 + TR_t)/9`)
- **색상 (한국/미국)**: 상승 `#ff4b4b` / 하락 `#1a9cff` (한국식)
- **세션 키**: `scr_` 접두사 필수 (한국은 `scr_kr_*` 추가 분리)
- **함수 접두사**: `us_`/`kr_` (데이터), `screen_` (로직), `ui_` (UI 헬퍼), `cache_` (캐시)

### 미국 필터 기준
- 최소 주가 $10, 20일 평균 거래대금 $20M, 변동폭 50% 이상 제외, 중국/관리 제외

### 한국 필터 기준 (2026-04-28 결정)
- **모집단 정적 제외**: 우선주 / 리츠 / ETF / 스팩 / 외국기업 (RS 의미 다름 또는 노이즈)
- **최소 주가**: 1,000원
- **20일 평균 거래대금**: 300억 원 이상 (원화 고정)
- **시가총액**: 3,000억 원 이상 (3e11) — 사이드바 슬라이더로 조정 가능
- **위험/관리종목**: 데이터 소스 보류 (KRX 익명 차단 + pykrx 인증 필요 + DART 키 미설정 — 거래대금/시총 필터로 자연 탈락 의존)

### UI / 테마 (2026-04-22)
- **라이트 테마** 고정 (`.streamlit/config.toml` `base = "light"`)
- 자산군 선택: 사이드바 최상단 `st.pills` (이전 상단 `st.tabs` 폐기)

## 알려진 이슈 / 제약
1. **yfinance 레이트 리밋 불안정** — 미국 3,800종목 전체 새로고침은 수십 분. 사이드바 `max_tickers` 제한 필수 (기본 200)
2. **`yf.Ticker().info` 느림** (요청당 0.3~1초) → 메타 TTL 7일
3. **장중 호출 시 당일 미완성 봉** — 변동성 필터 오작동 가능. 배치는 장 마감 후 권장
4. **한국 위험종목 필터 보류** — KRX 공시 익명 차단, pykrx 인증 필요, DART API 키 미설정. 사이드바 체크박스만 살아있음 (실제 적용 안 됨)
5. **한국 corporate action 자동 감지 미구현** — 분할/spin-off 발생 시 사용자가 force 수동 또는 stale-first 정렬에 의지
6. ~~**종목/지수 마지막일 미스매치 시 RS 시간 정합성 잃음**~~ — `screen_filter_by_index_lag` 로 해결됨 (2026-05-06)
7. **`dollar_volume` 컬럼명 한국에서 의미 어색** — 실제로는 원화 거래대금. Phase 4 통합 시 `traded_value` 등으로 일반화 검토
8. **차트 함수 미국/한국 중복** — `_us_render_chart` / `_kr_render_chart` 별도. 통화 단위만 다름. 추후 `_render_chart_panel(currency_symbol, price_format, dv_unit)` 일반화 후보
9. **한글 종목명** (미국) — 69종 시드, 필요 시 `data/us_ticker_kr.csv`에 추가
10. **Streamlit removeChild 워닝** — column 구조 hot reload 시 발생. Ctrl+Shift+R 로 해결
11. **장중 실시간 조회 미지원** — 일 1회 배치만

## 다음 작업 후보 (2026-05-06 갱신)
1. **corporate action 자동 감지** (yfinance Ticker.splits 비교) → 분할 발생 종목 자동 force fetch
2. **차트 함수 `_render_chart_panel` 일반화** (currency_symbol, price_format, dv_unit 인자화)
3. **위험종목 데이터 소스 결정** — KRX 회원 ID/PW 또는 DART API 키 셋업 후 `kr_risk.py` 추가
4. **`max_lag_days` 사이드바 슬라이더 노출** — 현재 0 하드코딩, 사용자가 너무 엄격하다 느끼면 1~5 조정 가능하게
5. **Phase 2 며칠 사용 후 피드백 모아 → Phase 3 코인 착수**

## 테스트 상태
- Phase 1 미국 (2026-04-21): 전체 파이프라인 스모크 OK — AAPL/MSFT/NVDA/BABA + ^IXIC, NVDA(1.335) > AAPL(0.794) > MSFT(0.744), BABA 중국 필터 제외
- Phase 2 한국 (2026-04-28): 5 KOSPI 종목 + KS11 20일 RS — SK하이닉스 1위 RS 1.893, 삼성전자우 2위 RS 1.270
- 모든 모듈 import OK (2026-05-04 재확인)
- Streamlit 실행 테스트는 사용자 진행 중 (`streamlit run screening.py` or `스크리닝 실행.bat`)

## 주요 커밋
- `80e758b` Phase 2 한국주식 본격 구현 + 사용자 결정 필터 + RS 정합성 fix
- `31a90fa` use_container_width 일괄 교체 + streamlit 최소 버전 상향
- `d7e7c36` UI 리뉴얼: 라이트 테마 전환 + 사이드바 자산군 pills + 포트 충돌 수정
- `5f04cfc` .claude/settings.local.json gitignore 추가
- `aedc99d` Phase 1.2~1.8 미국주식 MVP 전체 구현
- `ebfc6e4` Phase 1.1 프로젝트 스켈레톤 + 통합 대비 코딩 규칙
- `e0f4b0d` 프로젝트 초기화
