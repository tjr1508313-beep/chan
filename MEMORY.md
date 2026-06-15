# 스크리닝 프로젝트 메모리

> 분할 자동 감지 + 비번 잠금 추가 직후 스냅샷 — 2026-05-06 기준.
> Phase 1 (미국주식) 완료, Phase 2.1~2.7 + 2.11~2.13 완료, 2.8(사용자 실행 테스트) 진행 중.
> 클라우드 호스팅은 보류 (Oracle 가입 거부, Fly free tier 폐지) — 비번 코드는 미리 둠.

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
- `us_load_prices(ticker, days, with_actions=False) -> DataFrame` — yfinance, auto_adjust=True
  - `with_actions=True` 시 OHLCV + `Stock Splits` + `Dividends` (분할 감지용, 추가 API 호출 0)
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
- 테이블: `prices` (+traded_value 자동 — 미국 USD / 한국 KRW 거래대금), `metadata`,
  `index_prices`, `index_chart_snapshot`, `universe`, `screening_metrics`, `stock_returns`
- CRUD: `cache_save_prices/load_prices/save_meta/load_meta/save_index/load_index`
- 첫 화면 지수 차트: `cache_save_index_chart_snapshot/load_index_chart_snapshot`
  - 기존 스냅샷 + 신규 OHLC 병합 후 가장 늦은 날짜 1개 제외
  - 최근 완성 봉 110개만 저장하므로 사이트 진입 시 원시 지수 일봉 집계 없음
  - 구 원격 DB에 테이블이 없어도 로더는 빈 차트로 폴백하며,
    `screening.py`의 `_init_cache_once(schema_version=2)`가 배포 시 스키마를 보강
- 증분 커서: `cache_get_last_price_date`, `cache_get_last_index_date`
- 일괄 조회: `cache_get_all_last_price_dates()` — 한 SQL 로 모든 ticker 마지막일 (stale-first 정렬용)
- **신규** (2026-05-06): `cache_delete_prices(ticker)` — 분할 발생 시 옛 미조정 가격 통째로 삭제
- TTL 체크: `cache_meta_age_days`

### `screening/batch.py` (미국 오케스트레이션)
- `screen_refresh_prices(tickers, days=300, force=False, sleep_sec=0.2)`
  - **분할 자동 감지** (2026-05-06): last_before 있는 ticker 는 with_actions=True 로 받아
    Stock Splits 컬럼 검사 → 신규 split 발견 시 그 ticker 만 `cache_delete_prices` + force fetch
- `screen_refresh_meta(tickers, ttl_days=7, force=False, sleep_sec=0.3)`
- `screen_refresh_index(index_code, days=300, force=False)`
- 반환 (시세): `{"updated": int, "skipped": int, "failed": list[str], "force_refetched": int}`
- 반환 (메타/지수): `{"updated": int, "skipped": int, "failed": list[str]}`

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
- `render_screening_page()` — 미국/한국 한 화면 위·아래 배치 진입점
- spec dict 기반 공통화 (`_US_SPEC`, `_KR_SPEC`)
- 첫 화면 시장 요약 카드 아래에 선택 지수 최근 110일 완성 봉 미니 캔들 차트 표시
- 공유 헬퍼: `_render_screening_section`, `_render_sidebar`, `_render_rs_header`,
  `_render_pipeline_badge`, `_render_filter_summary`, `_render_ranking_table`,
  `_render_chart`, `_render_chart_metrics`, `_sort_tickers_stale_first`
- 차트: `streamlit-lightweight-charts-pro` 의 `Chart(series=[Candle+MA5/20/60+ATR])`
  로 통합. 5 시리즈 / 2 pane(price:ATR = 3:1) — 2026-05-18 Plotly 에서 교체

## 확정된 결정 사항

### MVP (2026-04-21)
- **RS 공식**: `종목 N일 수익률 - 지수 N일 수익률` — 지수와 같으면 0
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
3. **장중 호출 시 당일 미완성 종목 봉** — 종목 변동성 필터 오작동 가능. 배치는 장 마감 후 권장.
   첫 화면 지수 차트는 배치가 가장 늦은 날짜 봉을 제외해 별도 보호.
4. **한국 위험종목 필터 보류** — KRX 공시 익명 차단, pykrx 인증 필요, DART API 키 미설정. 사이드바 체크박스만 살아있음 (실제 적용 안 됨)
5. **한국 corporate action 자동 감지 미구현** — FDR 에 splits API 없음. 사용자가 force 수동 또는 stale-first 정렬에 의지 (미국은 2026-05-06 자동화 완료)
6. ~~**종목/지수 마지막일 미스매치 시 RS 시간 정합성 잃음**~~ — `screen_filter_by_index_lag` 로 해결됨 (2026-05-06)
7. ~~**`dollar_volume` 컬럼명 한국에서 의미 어색**~~ — `traded_value` 로 통일 완료 (2026-05-18). `init_cache()` 마이그레이션이 구 DB 자동 변환.
8. ~~**차트 함수 미국/한국 중복**~~ — `_render_chart(spec, ...)` 단일 함수로 통합 완료 (자산군 spec dict 분기). 2026-05-18 LWC 교체와 함께 정리.
9. **한글 종목명** (미국) — 69종 시드, 필요 시 `data/us_ticker_kr.csv`에 추가
10. **Streamlit removeChild 워닝** — column 구조 hot reload 시 발생. Ctrl+Shift+R 로 해결
11. **장중 실시간 조회 미지원** — 일 1회 배치만

## 다음 작업 후보 (2026-05-18 갱신 — 차트 LWC 교체 / 컬럼명 일반화 완료)
1. **`max_lag_days` 사이드바 슬라이더 노출** — 현재 0 하드코딩, 사용자가 너무 엄격하다 느끼면 1~5 조정 가능하게
2. **위험종목 데이터 소스 결정** — KRX 회원 ID/PW 또는 DART API 키 셋업 후 `kr_risk.py` 추가
3. **한국 분할 감지** — FDR 자체 splits API 없음. KRX 공시 또는 가격 점프 휴리스틱으로 우회 검토
4. **차트 인터랙션 강화** — LWC 의 tooltip / 범례 / range switcher 옵션 활용 검토
5. **Phase 2 며칠 사용 후 피드백 모아 → Phase 3 코인 착수**
6. **(보류) 클라우드 호스팅** — Oracle/Fly 모두 막힘. 무료+영속+24/7 옵션 사라짐. 비번 코드는 미리 둠

## Google Drive 관심종목 동기화 (2026-06-15)
- 나무증권 관심종목 CSV는 EUC-KR `INTR_EXCEL` 형식으로 생성한다.
- 로컬 실행은 프로젝트 폴더에 직접 저장한다.
- Streamlit Cloud는 사용자 PC 파일에 접근할 수 없어 `screening/drive_upload.py`가
  Google Apps Script 웹 앱으로 CSV 바이트를 전송한다.
- Apps Script는 EUC-KR 바이트 보존을 위해 기존 동명 파일을 휴지통으로 이동하고
  새 blob 파일로 교체한다. `setContent()` 사용 금지.
- Cloud secrets: `google_drive_upload_url`, `google_drive_upload_token`
- 설정 가이드: `docs/google-drive-watchlist-setup.md`

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
