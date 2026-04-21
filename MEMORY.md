# 스크리닝 프로젝트 메모리

> Phase 1 (미국주식 MVP) 완료 기준 스냅샷. 이어 작업할 때 참고용.

## 프로젝트 구조
```
C:\스크리닝\
├── screening.py             # Streamlit 진입점 (main)
├── screening/               # 로직 패키지 (통합 시 통째로 이동 대상)
│   ├── __init__.py
│   ├── ui.py                # Streamlit 탭 UI (render_us_tab/kr/crypto)
│   ├── core.py              # RS 계산, 필터링, 랭킹
│   ├── cache.py             # SQLite 캐시 CRUD
│   ├── batch.py             # 배치 오케스트레이션 (refresh_prices/meta/index)
│   ├── data.py              # yfinance + FDR 외부 API
│   ├── china_filter.py      # 중국기업 판정
│   └── theme.py             # 다크 테마 CSS
├── data/
│   ├── china_stocks.csv     # 중국 ADR 시드 30개
│   └── us_ticker_kr.csv     # 한글명 매핑 69개 (확장 가능)
├── screening_cache.db       # SQLite 영속 캐시 (gitignored)
├── requirements.txt         # `>=` 최소 버전
└── CLAUDE.md                # 프로젝트 규칙 (통합 대비 코딩 규칙 포함)
```

## 핵심 함수 레퍼런스

### `screening/data.py` (외부 API)
- `us_get_nasdaq_tickers() -> list[str]` — FDR, 약 3,860개
- `us_get_sp500_tickers() -> list[str]` — FDR, 약 503개
- `us_load_prices(ticker, days) -> DataFrame` — yfinance, auto_adjust=True, OHLCV
- `us_load_index(index_code, days) -> DataFrame` — `^IXIC`/`^GSPC`
- `us_get_meta(ticker) -> dict` — name_en/name_kr/sector/country/exchange/market_cap/is_china/is_risk
- `us_get_kr_name(ticker) -> str | None` — CSV 매핑 조회

### `screening/cache.py` (SQLite)
- DB: `screening_cache.db` (프로젝트 루트 고정)
- 테이블: `prices` (+dollar_volume 자동), `metadata`, `index_prices`, `settings`
- CRUD: `cache_save_prices/load_prices/save_meta/load_meta/save_index/load_index`
- 증분 커서: `cache_get_last_price_date`, `cache_get_last_index_date`
- TTL 체크: `cache_meta_age_days`

### `screening/batch.py` (오케스트레이션)
- `screen_refresh_prices(tickers, days=300, force=False, sleep_sec=0.2)`
- `screen_refresh_meta(tickers, ttl_days=7, force=False, sleep_sec=0.3)`
- `screen_refresh_index(index_code, days=300, force=False)`
- 반환: `{"updated": int, "skipped": int, "failed": list[str]}`

### `screening/core.py` (로직)
- `screen_build_screening_df(tickers, lookback_days=20)` — 캐시 집계 wide DF
- `screen_apply_filters(df, config) -> (df, stats)` — 5종 필터, 순서: price→volume→risk→china→volatility
- `screen_calc_rs(prices, index_prices, period=20)` — 단일/wide 지원
- `screen_rank_rs(tickers, index_code, period=20, top_n=20) -> DataFrame`

## 확정된 결정 사항 (2026-04-21)
- **RS 공식**: `(종목 N일 수익률) / (지수 N일 수익률)`, epsilon 1e-9
- **필터 기준**: 최소주가 $10, 최소 20일 평균 거래대금 $20M, 변동폭 50% 이상 제외, 중국/관리 제외
- **변동폭 공식**: `(H - L) / prev_close`
- **ATR 공식**: Wilder 9일 (`ATR_t = (ATR_{t-1}*8 + TR_t)/9`)
- **색상**: 상승 `#ff4b4b` / 하락 `#1a9cff` (한국식)
- **세션 키**: `scr_` 접두사 필수
- **함수 접두사**: `us_` (데이터), `screen_` (로직), `ui_` (UI 헬퍼), `cache_` (캐시)

## 알려진 이슈 / 제약
1. **yfinance 레이트 리밋 불안정** — 3,800종목 전체 새로고침은 수십 분. UI 사이드바에서 `max_tickers` 제한 필수 (기본 200)
2. **`yf.Ticker().info` 느림** (요청당 0.3~1초) → 메타 TTL 7일
3. **장중 호출 시 당일 미완성 봉** — 변동성 필터 오작동 가능. 배치는 장 마감 후 권장
4. **한글 종목명** 69종만 시드 — 필요 시 `data/us_ticker_kr.csv`에 추가
5. **`is_risk` MVP 수준** — `quoteType != EQUITY`, market_cap None/0, regularMarketPrice None. SEC/NYSE 공시 기반 정교화는 향후 과제
6. **장중 실시간 조회 미지원** — 일 1회 배치만
7. **auto_adjust 과거 거래대금** — 분할 이력 있는 티커의 과거 dollar_volume은 조정값. 상대 비교엔 무해

## 테스트 상태 (2026-04-21)
- 전체 파이프라인 스모크 OK: AAPL/MSFT/NVDA/BABA + ^IXIC
  - 지수 ^IXIC 20일 수익률 +12.73%
  - 랭킹: NVDA(1.335) > AAPL(0.794) > MSFT(0.744) (BABA 중국 필터에서 제외)
- 모든 모듈 import 에러 없음
- Streamlit 실행 테스트는 사용자 몫 (`streamlit run screening.py` or `스크리닝 실행.bat`)

## 다음 단계 후보
- **즉시**: 사용자가 `streamlit run` 으로 실 환경 UI 검수 → 버그 있으면 `/fix-bug`
- **Phase 1 보강**: 한글명 CSV 확장 (현 69 → 200), SEC 기반 is_risk 정교화
- **Phase 2**: 한국주식 (pykrx/FDR, 코스피/코스닥 RS)
- **Phase 3**: 코인 (바이낸스 API, BTC 대비 RS)
- **Phase 4**: 매매일지 통합 (사용자가 직접 루트 폴더 통합)
- **공식 개선 검토**: 블로그(best-n-optimal) 가중 합산 방식 `0.4·R63 + 0.2·R126 + 0.2·R189 + 0.2·R252`

## 주요 커밋
- `ebfc6e4` Phase 1.1 프로젝트 스켈레톤 + 통합 대비 코딩 규칙
- `e0f4b0d` 프로젝트 초기화
- (이번 Phase 1.2~1.8 작업은 아직 미커밋 — `/scr-commit` 대기)
