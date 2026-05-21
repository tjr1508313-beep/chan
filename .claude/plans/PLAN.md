# 주식 스크리닝 프로젝트 계획서

## 프로젝트 개요
상대강도(RS) 기반 주식 스크리닝 툴. 지수 대비 강한 종목 상위 N개를 자동 추출하고,
5MA + 9ATR 차트로 빠르게 검토. 미국주식 + 한국주식을 **한 화면**에 위/아래로 표시.

## 자산 확장 로드맵
1. **Phase 1 — 미국주식 MVP** ✅ 완료 (2026-04-21)
2. **Phase 2 — 한국주식** ✅ 구현 완료 (2026-04-28~05-06), 사용자 실사용 중
3. **Phase 3 — 매매일지 통합** (사용자가 직접 루트 폴더 통합)

---

## Phase 1: 미국주식 MVP ✅ 완료 (2026-04-21)

나스닥 / S&P 500 RS Top N 스크리닝. 아래 항목 전부 구현 완료.

- **스켈레톤**: `screening/` 서브패키지 + `screening.py` 진입점, SQLite 캐시
- **데이터**: yfinance(시세/지수/메타) + FDR(종목 리스트), 중국기업 필터 2단계 판정
- **캐시**: SQLite 4테이블(`prices`/`metadata`/`index_prices`/`settings`) + `batch.py` 증분 오케스트레이션
- **필터 5종**: 가격 / 거래대금 / 관리종목 / 중국기업 / 변동성(`(H-L)/prev_close ≥ 50%`)
- **RS 공식**: 단순 비율 `RS = (종목 N일 수익률) / (지수 N일 수익률)`, 기본 20일·슬라이더 5~60일
- **UI**: 사이드바(지수/기간/TopN/필터) + 좌측 랭킹 테이블 + 우측 Plotly 차트(캔들 + 5MA + 9ATR Wilder)
- **한글명**: `data/us_ticker_kr.csv` 수동 매핑

---

## Phase 2: 한국주식 확장 ✅ 구현 완료 (2026-04-28 ~ 2026-05-06)

코스피(`KS11`) / 코스닥(`KQ11`) RS 스크리닝. 미국 코드와 spec dict 로 공통화.

### 확정 사항
- **데이터 소스**: FDR 단일 (`StockListing`, `DataReader`) — pykrx 는 KRX 익명 차단으로 제외
- **거래대금**: `Close × Volume`, 필터 기준 300억 원 이상
- **한글명**: FDR `StockListing.Name` 그대로 사용
- **티커**: 6자리 숫자 → 미국 영문 티커와 자연 분리, 같은 캐시 DB 공유

### 구현 완료 항목
- `data_kr.py` / `batch_kr.py` — 미국과 대칭 구조
- `core.py` 수정 0줄로 KR 데이터 동작 (spec 분기)
- UI: `_render_screening_section` 공통화, session_state `scr_kr_*` 분리
- 모집단 정적 제외: 우선주 / 리츠 / ETF / 스팩 / 외국기업 (`data_kr._apply_universe_filter`)
- 시가총액 필터 ≥ 3,000억 원 (`core.py` 신규 단계 + UI 슬라이더)
- RS 시간 정합성: `screen_filter_by_index_lag` — 종목 캐시 마지막일이 지수보다 뒤처지면 제외
- 분할 자동 감지(미국): `_detect_new_split` — 새 split 발견 시 해당 ticker force 재다운로드
- 비밀번호 잠금 게이트: `auth.py: require_password()` — secrets 미설정 시 자동 비활성

### 보류 항목
- ~~**관리종목/위험종목 필터 데이터 소스**~~ → **해소 (2026-05-21)**: LS증권 REST OpenAPI 로 관리/거래정지/정리매매 제외 적용 (아래 별도 섹션 참고). KIS 대신 LS 채택.

### 잔여 (사용자 몫)
- 사용자 실행 테스트 / 한국 휴장일 점검 (FDR 이 영업일만 반환하므로 큰 이슈 없을 것으로 예상)

---

## 급락 차단 필터 추가 ✅ (2026-05-16)

RS 산출 시점에 직전 1~2일 동안 큰 음봉을 맞은 종목을 매수하지 않도록 필터 추가.

### 규칙
- D-0(오늘) 또는 D-1(어제) 일봉 **종가 하락폭** ≥ 9일 ATR(직전일까지) × `max_atr_drop_multiple` 이면 제외
- 기본 임계값 **2.5배**, 사이드바 슬라이더 1.0~5.0 + 체크박스로 조정/비활성
- 분모는 **그 봉의 직전일까지 ATR9** — 큰 하락이 당일 ATR에 즉시 반영돼 필터가 무력화되는 lookahead bias 회피

### 변경 파일
- `core.py`:
  - `calc_wilder_atr` 를 ui 에서 옮겨 streamlit-free 영역(core)에 배치, public 노출
  - 새 헬퍼 `_recent_atr_drop_multiple(prices, atr_period=9, lookback=2)`
  - `_SCREEN_DF_COLUMNS` 에 `recent_atr_drop_mult` 컬럼 추가, `screen_build_screening_df` 에서 계산
  - `_default_config` 에 `max_atr_drop_multiple: 2.5`, `screen_apply_filters` 7번째 단계 + `after_atr_drop` 통계
- `ui.py`:
  - `calc_wilder_atr` core 에서 import (차트 ATR 계산도 동일 함수 공유)
  - 사이드바 필터 expander 에 체크박스 + 슬라이더, `filter_config["max_atr_drop_multiple"]` 추가
  - 파이프라인 배지에 "급락 N", 필터 요약에 "급락 < ATR×2.5" 배지

### 적용 범위
- 미국·한국 양 자산군 동일 (spec 분기 불필요 — RS 정합성 검사와 같은 위치)

---

## UI 개편 — 한 화면 통합 + 독립 새로고침 ✅ (2026-05-15)

- **미국 + 한국을 한 화면에**: 자산군 사이드바 탭(`st.pills`) 제거.
  `render_screening_page()` 가 위=미국 / 아래=한국 으로 두 섹션을 세로 배치.
  사이드바엔 미국·한국 설정이 위아래로 함께 나열.
- **새로고침 독립 실행**: `_render_refresh_section` + `_refresh_worker`(백그라운드 스레드)
  + `_render_refresh_progress`(`@st.fragment(run_every=2)` 폴링).
  미국이 도는 동안 한국 버튼을 따로 눌러 동시 진행 가능. 진행바는 job dict 폴링으로 표시.
  - 스레드는 batch 함수(순수 파이썬)만 호출 — Streamlit API 미사용으로 ScriptRunContext 불필요.
  - `cache.py: _connect` 에 `PRAGMA busy_timeout=30000` — 두 스레드 동시 쓰기 락 경합 대비.
- **`init_cache()` 앱 시작 시 호출**: 캐시 DB 없는 새 환경에서도 읽기 경로 크래시 방지.

---

## 자동 갱신 — GitHub Actions ✅ (2026-05-15)

평일 장 종료 후 캐시 DB 자동 갱신 → 로컬 앱 시작 시 자동 동기화.

### 추가된 컴포넌트
- `scripts/refresh_cache.py` — 헤드리스 CLI (`--market us|kr`). batch 함수만 호출.
- `.github/workflows/refresh-us.yml` / `refresh-kr.yml` — 평일 cron + 텔레그램 알림
  - data-cache 브랜치에 orphan force-push 로 히스토리 1개만 유지 (~30MB binary)
  - 실패/예외 시 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` Secrets 로 텔레그램 발송
- `screening/cache_sync.py` — `last_updated.txt` 비교 후 변경 시 DB 다운로드
  - 임시파일 → `os.replace()` 원자 교체, WAL/SHM 사이드카 정리
  - `requests` 우선, 없으면 `urllib` 폴백 — 외부 의존 추가 없음
  - 환경변수 `SCREENING_SKIP_REMOTE_SYNC=1` / `SCREENING_CACHE_REPO=owner/repo`
- `screening.py` 진입점에 `@st.cache_resource _sync_remote_cache_once()` — 프로세스당 1회만 호출
- `ui.py: _render_remote_sync_badge` — 사이드바 상단에 마지막 동기화 시각 + "지금 받기" 버튼

### 결정 사항
- **갱신 범위 = 지수 + 시세 + 메타** (메타는 TTL 7일 증분 — 평소엔 대부분 skip, 만료/신규만 외부 호출. 2026-05-20 정책 변경: Streamlit Cloud 에서 종목명/시총이 비어 뜨는 문제 해결을 위해 메타까지 포함하도록 확장)
- **DB 보관 = data-cache orphan 브랜치** (Release Asset 대비 권한·인증 단순)
- **알림 = 실패 시만 텔레그램** (성공은 조용)
- **일정 (cron)** — primary + 백업 2 (2026-05-19 다중화):
  - KR: `40 6 / 10 7 / 40 7 * * 1-5` UTC = 평일 KST **15:40 / 16:10 / 16:40**
  - US: `0 22 / 30 22 / 0 23 * * 0-4` UTC = 평일 KST **07:00 / 07:30 / 08:00**
  - `precheck` job 이 같은 날 `data-cache:last_updated.txt` 확인 후 이미 성공이면 스킵 (workflow_dispatch 는 항상 실행)
  - 동기: GitHub Actions 무료 플랜의 schedule 트리거가 부하 시간대에 누락/지연되는 알려진 한계 대응
    (실제 사례: 2026-05-19 KR 트리거 누락, 2026-05-18 KR 4시간 지연)

### 사용자 1회 세팅 (잔여)
- 레포 Settings → Secrets 에 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 입력
- Actions 탭에서 첫 워크플로우 수동 트리거 (또는 그냥 다음 평일 자동 실행 대기)
- 가이드: `docs/auto-refresh-setup.md`

---

## Phase 3: 매매일지와 통합 (사용자 담당)
- 사용자가 직접 `C:\테스트\`(매매일지) + `C:\스크리닝\` 을 상위 폴더로 묶음
- 하나의 Streamlit 앱에서 좌측 사이드바로 [매매일지] [스크리닝] 전환
- DB 파일은 분리 유지 권장 (`trading_journal.db`, `screening_cache.db`)

---

## 차트 교체 — Plotly → TradingView Lightweight Charts ✅ (2026-05-18)

차트 라이브러리를 Plotly Candlestick 서브플롯에서 TradingView 의
`streamlit-lightweight-charts-pro` 로 교체.

### 동기
- TradingView 스타일의 시각적 일관성 (캔들 두께, 십자선, 마지막 값 라벨)
- HTML5 canvas 기반으로 종목 전환 시 더 가볍게 다시 그려짐
- 기본 제공 인터랙션(crosshair, pan, zoom) 이 Plotly보다 직관적

### 변경 사항
- `requirements.txt`: `plotly>=5.18` 제거, `streamlit-lightweight-charts-pro>=0.3` 추가
- `screening/ui.py` `_render_chart` 전면 재작성:
  - `CandlestickSeries` (한국식 적/청)
  - `LineSeries` × 3: MA5(주황) / MA20(녹) / MA60(보라) — 모두 pane 0
  - `LineSeries` × 1: 9-day ATR Wilder (인디고) — pane 1
  - `ChartOptions(layout=LayoutOptions(pane_heights={0: factor=3, 1: factor=1}))`
    로 가격/ATR 패널 = 3:1 비율
  - Pretendard 폰트 우선 적용
  - 차트 위에 `{ticker} · 가격 (날짜)` 타이틀 (LWC 에 title 옵션 없음)
- `ui_load_chart_df(days)` 요구 데이터를 `lookback + 70` 으로 확장 (MA60 부트스트랩 분)
- 색상 상수: `_COLOR_MA` → `_COLOR_MA5`, `_COLOR_MA20`(#22c55e), `_COLOR_MA60`(#a855f7) 추가.
  `_COLOR_ATR_FILL` 제거(Plotly 전용)
- 차트 `key=f"lwc_chart_{spec['code']}_{ticker}"` — 티커 전환 시 재마운트 보장

### 검증
- 단위: 객체 그래프(5 시리즈, pane_ids=[0,0,0,0,1], 색상/높이/key) 일치 확인
- 통합: `_chart_preview.py` mini 페이지로 LWC iframe 마운트 + 11 canvas 렌더 +
  픽셀 샘플링으로 캔들 적/청 + MA5/20/60 + ATR 색상 모두 화면에 그려짐 확인

### 주의
- LWC 는 OHLC 유효성 검증(`open ≤ high`) — 실데이터는 항상 유효해서 문제 없음
- Streamlit DataFrame(glide canvas) 행 선택 → rerun → `_render_chart` 호출 흐름은
  Plotly 시절과 동일

---

## 컬럼명 일반화 ✅ (2026-05-18)

`dollar_volume` 컬럼명이 한국주식 맥락에서 의미 어색 (실제는 원화 거래대금) → `traded_value` 로 통일.

### 변경 범위
- `cache.py`: DDL `dollar_volume REAL` → `traded_value REAL`, INSERT/SELECT 쿼리, docstring
- `cache.py`: `_migrate_dollar_volume_column()` — 구 스키마 자동 RENAME COLUMN (SQLite 3.25+)
  - `init_cache()` 매 호출 시 PRAGMA 검사. 원격 동기화로 들어온 구 DB 도 처리.
- `core.py`: `_avg_dollar_volume` → `_avg_traded_value`, `avg_dollar_volume_20d` 컬럼,
  `min_dollar_volume` config 키
- `ui.py`: 필터 config 키, 랭킹 테이블 컬럼 참조, 차트 메트릭

### 호환성
- 신규 DB 는 새 컬럼명으로 즉시 생성
- 기존 로컬 DB / 원격 동기화로 들어온 구 DB 는 `init_cache()` 1회로 자동 변환
- GitHub Actions 워크플로우는 다음 실행 시 새 스키마 DB 생성 (코드 동일 패키지 사용)

---

## RS 가중 합산 컬럼 추가 ✅ (2026-05-19)

기존 단순 비율 RS와 Minervini 가중 RS를 나란히 표시. 테이블 위 `st.pills` 로 정렬 전환.

### 구현 내용
- `core.py`:
  - `_WEIGHTED_PERIODS = [(63,0.4),(126,0.2),(189,0.2),(252,0.2)]` 상수
  - `_calc_weighted_rs(close)` — `(C/C63)×0.4 + (C/C126)×0.2 + (C/C189)×0.2 + (C/C252)×0.2`
  - `screen_rank_rs()` — `days`를 `max(period+10, 263)`으로 확장, `rs_weighted` 컬럼 추가
  - `_RANK_DF_COLUMNS`에 `rs_weighted` 추가
- `ui.py`:
  - 테이블 위에 `st.pills` 로 "RS" / "RS가중" 정렬 선택
  - 활성 컬럼 헤더에 ▼ 표시 + bold 강조 (markdown 만 사용)
  - "RS가중" 셀 추가, 252일 부족 종목은 "—" 표시
  - 행 셀 버튼 key 를 **ticker 기반** 으로 변경 — 정렬 시 React reconciliation 오류 방지

### 동작 방식
- 기본 정렬: `rs` (단순 비율 20일)
- pills 로 RS / RS가중 선택 → 해당 컬럼 내림차순, 순위 재번호
- 252영업일 미만 종목은 `rs_weighted = NaN` → 정렬 시 맨 아래, 표시는 "—"
- top_n 컷은 `rs` 기준 유지 (screen_rank_rs), UI에서 재정렬만

### 시행착오 — 같은 함정 다시 밟지 말 것 ⚠️
구현 중 발생했던 오류와 해결책 — 비슷한 UI 작업 시 미리 체크할 항목:

1. **`NameError: name 'components' is not defined`** (theme.py)
   - 원인: `components.html(_NOTRANSLATE_JS, ...)` 사용하면서 `import streamlit.components.v1 as components` 누락
   - 교훈: `apply_theme()` 등에서 `components.html()` 호출 시 임포트 확인 필수

2. **Chrome 자동번역이 다시 동작 (MRAM → 엠람)**
   - 원인: `_NOTRANSLATE_JS` 가 `var p = window.document` 로 iframe 내부 문서만 건드림
   - 해결: `var p = window.parent.document` — `st.components.v1.html()` 은 iframe 안에서 실행되므로 부모를 잡아야 메인 페이지에 `translate=no` / `notranslate` 적용됨
   - 교훈: components.html 안의 JS 는 항상 `window.parent.document` 사용

3. **`NotFoundError: 'removeChild' 실패` (DOM reconciliation 오류)**
   - 원인: 행 셀 버튼 key 가 `f"...{row_pos}_{c_idx}"` 로 **위치 기반** → 정렬 변경 시 같은 key 에 다른 종목이 들어와 React 가 노드 식별 혼동
   - 해결: key 를 `f"...{ticker}_{c_idx}"` 로 **identity 기반** 변경 — React 가 행을 "이동" 으로 인식
   - 교훈: 재정렬 가능한 동적 리스트에서 element key 는 항상 데이터 identity 기반

4. **헤더 버튼 클릭 정렬 방식이 시각적으로 안 보임**
   - 원인: `div.st-key-scr_rank_header_*` 컨테이너의 헤더 버튼 텍스트가 Streamlit 기본 버튼 스타일과 충돌 → CSS specificity 문제로 텍스트 안 보임
   - 해결: 헤더 버튼 방식 폐기하고 테이블 위 `st.pills` 로 정렬 선택
   - 교훈: Streamlit nested 컨테이너 + 커스텀 CSS 는 specificity 가 까다로움. 명확한 위젯(`st.pills`, `st.radio`) 이 안전

5. **워크트리에만 변경 적용되고 메인 프로젝트에 반영 안 됨**
   - 원인: Claude Code 가 워크트리(`.claude/worktrees/...`) 에서 작업 중인데 사용자는 메인(`C:\스크리닝`) 에서 앱 실행
   - 해결: 변경을 양쪽에 모두 적용 또는 워크트리에서 작업 후 main 으로 merge
   - 교훈: 워크트리 작업 시작 시 사용자가 어디서 앱을 실행하는지 확인. 둘 다 commit 해야 함

---

## 로딩 속도 개선 + 차트 버그 수정 ✅ (2026-05-20)

### 1) 전 종목 일괄조회 (로딩 속도 ~6배)
- 문제: `screen_build_screening_df` / `screen_rank_rs` 가 종목별로 `cache_load_prices`+`cache_load_meta`
  를 개별 호출 → 커넥션 open/close + 쿼리 왕복이 수천 번. 실측 종목당 34ms → 나스닥 ~129초.
- 해결: `cache.py` 에 **일괄 로더 추가**
  - `cache_load_prices_bulk(tickers, days)` — TEMP 테이블 `_wanted` 에 대상 티커를 넣고
    JOIN + `ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC)` 로 종목별 최근 N행을
    쿼리 1회에 조회 후 pandas groupby 분리. (윈도우 함수를 전체 테이블이 아닌 대상 종목으로 한정)
  - `cache_load_meta_bulk(tickers)` — 메타 전체 1회 조회 후 대상만 dict 반환
- `core.py` 두 함수가 bulk dict 에서 읽도록 변경 (결과 동일성 검증: 단일 vs 일괄 0 불일치)
- 실측: KR 2515종목 build 85초→~15초, US 4219종목 129초→~22초. (결과는 `ui_load_ranked_df` ttl=300 캐시)

### 2) 0값 OHLC 행 보정 (캔들/ATR 폭주 수정)
- 문제: FDR 한국 데이터에서 거래 없는 날 등에 `Open/High/Low = 0` (Close만 유효) 행 발생.
  차트가 `high=max(OHLC)`, `low=min(OHLC)=0` 으로 잡아 **0에서 솟는 거대 캔들** + ATR True Range 폭주.
- 해결: `cache.py: _repair_ohlc()` — O/H/L 이 0/결측이면 같은 행 Close 로 채워 doji 처리.
  `cache_load_prices` + `cache_load_prices_bulk` 양쪽에 적용. Close만 쓰는 RS/거래대금엔 영향 없음.
  ATR-drop 필터(스크리닝)와 차트 ATR 패널 모두 정상화.

### 3) 차트 날짜축 버그 (00:00 표시) 수정
- 문제: `TimeScaleOptions.time_visible` 기본 **True** → 일봉인데 축/크로스헤어에 "00:00" 시각 표시.
  추가로 naive datetime 을 서버 로컬 타임존으로 해석 → 로컬(KST)/클라우드(UTC) 날짜 어긋남.
- 해결: `ui.py: _render_chart`
  - `ChartOptions(time_scale=TimeScaleOptions(time_visible=False, seconds_visible=False))`
  - `view_times = df_view.index.tz_localize("UTC")` 로 캔들/라인 time 을 UTC 자정 고정 →
    어느 환경에서나 동일 날짜로 표시 (검증: tz-aware UTC midnight → 정확한 epoch, config 에 timeVisible:false)

### 4) 차트 좌상단 이평선 범례
- `_render_chart` 타이틀 아래에 색칩 + 라벨 (● MA5 / ● MA20 / ● MA60) markdown 추가.

> ⚠️ 미검증: 1~4 모두 데이터/객체 레이어까지 검증. 브라우저 실제 렌더(범례 표시·축 날짜)는
> Streamlit 실행 환경이 필요해 코드 자동검증으로 대체 — 사용자 육안 확인 필요.

---

## 로딩 속도 개선 2탄 — 유니버스 캐싱 + 죽은 티커 정리 + ATR 최적화 ✅ (2026-05-21)

증상: 앱 첫 로드가 수분간 안 뜸. 원인 분석 결과 (서버 자체는 정상, 헬스 0.002s):
화면 첫 로드가 미국·한국 섹션 전체 스크리닝을 동기 블로킹하며, 그 안에서
**① FDR 티커목록 네트워크 호출(나스닥 7s+, 느린 날 수분~행)**, ② 200MB DB 읽기,
③ 3,800종목 파이썬 루프(~15s)가 누적. 콜드 디스크 + 느린 네트워크가 곱해져 "안 뜸".

### 1) 유니버스 DB 캐싱 (네트워크 구간 제거)
- `cache.py`: `universe(index_code, ticker, updated_at)` 테이블 신설 +
  `cache_save_universe()` / `cache_load_universe()`
- `ui.py`: `ui_load_index_tickers()` → DB 우선, 비었을 때만 FDR 폴백 후 저장.
  `ui_refresh_index_universe()` (갱신 경로 전용, 항상 FDR→저장) 추가.
- 갱신 경로(`refresh_cache.py` `_refresh_us/_refresh_kr`, `_start_refresh`)가
  FDR 최신 목록을 받아 universe 저장. → 화면 로드 시 티커목록 7.4s → **0.01s**.

### 2) 죽은 티커 자동 정리 (날짜 트리밍은 안 함)
- `cache.py`: `cache_prune_orphan_prices(vacuum=False)` — 현재 universe 에 없는
  티커의 시세 행 삭제. universe 비면 아무것도 안 지움(안전장치).
- 호출: 갱신 워커 끝(`vacuum=False`), `refresh_cache.py`(`vacuum=True`),
  `cache_sync._apply_remote` merge 후(`vacuum=False` — merge 가 죽은 티커 되살림 방지).
- 일회성 청소 스크립트 `scripts/prune_db_once.py` (universe 채우기+prune+VACUUM).
- ⚠️ **날짜 트리밍 안 함** (사용자 결정 — 장기 차트 위해 전체 기간 누적).
- 실측: 죽은 티커는 2,058행뿐 → DB 211MB→201MB (큰 효과 아님). 진짜 효과는 ①③.

### 3) ATR 계산 numpy 최적화
- `core.py` `calc_wilder_atr`: Wilder 평활 루프를 pandas `.iloc[]` → numpy 배열로.
  결과값 동일(검증: 5종목 ATR 최근15봉 비교 불일치 0). 나스닥 빌드 21.7s→15.7s.

### 검증
- 단위: ATR 신·구 동일, 임포트 OK, universe 4지수 적재(3868/503/811/1725).
- 통합: 실제 DB+코드로 streamlit 기동 → 미국·한국 양 섹션 랭킹+차트 정상 렌더,
  에러 없음. 파이프라인 워밍 기준 나스닥 32s→18s, 섹션합 최악 32s→18s + 5분 캐시.

### 잔여
- `screening_cache.db.prebackup` (211MB) — 정상 확인 후 사용자가 삭제하면 됨.

---

## 한국 관리종목 필터 (LS증권 OpenAPI) ✅ (2026-05-21)

KRX 익명 차단으로 보류했던 관리종목 필터를 LS증권 REST OpenAPI 로 해소.

### 규칙
- **제외(is_risk=True)**: 관리종목 · 거래정지 · 정리매매
- **참고 배지만 (제외 X)**: 투자경고 · 투자주의 · 단기과열
- 데이터 갱신: 메타 갱신 *후* 매 새로고침마다 `screen_refresh_risk_kr()` (시장경보·단기과열 일변동 대응, 7일 메타 TTL 과 분리)
- 키 미설정/API 실패 시 graceful degrade (플래그 미변경, 갱신 정상 완료)

### 변경 파일
- `screening/kr_risk.py` (신규) — LS OpenAPI 클라이언트 + 지정 분류 (`_classify`)
- `screening/cache.py` — `metadata.caution_flags` 컬럼 + `_migrate_caution_flags_column` + `update_risk_flags` (한국 6자리 티커만 클리어해 미국 `is_risk` 보존) + `cache_load_meta_bulk` 에 `caution_flags` 포함
- `screening/batch_kr.py` — `screen_refresh_risk_kr()` (빈 flags 시 skip)
- `scripts/refresh_cache.py` — `_refresh_kr()` 에서 메타 뒤 플래그 패스 호출
- `screening/core.py` — `_SCREEN_DF_COLUMNS` + build 에 `caution_flags` (표시 전용)
- `screening/ui.py` — `_caution_badge_md` 참고 배지 + `exclude_risk` 라벨/help
- `screening.py` — `st.secrets` → `os.environ` (LS_APP_KEY/SECRET)
- `.github/workflows/refresh-kr.yml` — LS 키 env 주입

### 사용자 1회 세팅 (잔여)
- LS증권 계좌 + OpenAPI 앱 등록 → **조회전용** App Key/Secret 발급
- 로컬 `.streamlit/secrets.toml` 에 `ls_app_key`/`ls_app_secret`
- GitHub Secrets 에 `LS_APP_KEY`, `LS_APP_SECRET`
- `kr_risk._collect_raw_designations` 의 tr_cd/path/InBlock/`_parse_block` 을 LS 라이브 테스트베드 응답에 맞춰 확정 (현재 t1404/t1405 플레이스홀더)

---

## 미결정 (추후 확장 시 논의)
- [ ] 장중 실시간 조회 지원 여부 (현재는 장 마감 후 배치만)
