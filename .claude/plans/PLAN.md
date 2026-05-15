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
- **관리종목/위험종목 필터 데이터 소스** — KRX 공시 익명 차단, pykrx 1.2.7 에 admin/warning 함수 없음.
  UI 체크박스만 노출, 데이터 미적용. 시총 3,000억 + 거래대금 300억 + 변동성 필터로 자연 탈락 의존.
  - 해소 옵션: KIS OpenAPI 도입 (사용자 한투 계좌 보유). 현재 보류 — FDR 정상 작동 중이라 트리거 미충족.

### 잔여 (사용자 몫)
- 사용자 실행 테스트 / 한국 휴장일 점검 (FDR 이 영업일만 반환하므로 큰 이슈 없을 것으로 예상)

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
- **갱신 범위 = 지수 + 시세만** (메타 제외 — 7일 TTL 이라 분기 1회 수동으로 충분)
- **DB 보관 = data-cache orphan 브랜치** (Release Asset 대비 권한·인증 단순)
- **알림 = 실패 시만 텔레그램** (성공은 조용)
- **일정 (cron)**:
  - KR: `40 6 * * 1-5` UTC = 평일 KST 15:40 (장 종료 KST 15:30 + 10분 여유)
  - US: `0 22 * * 0-4` UTC = 평일 KST 07:00 (장 종료 KST 06:00 + 1시간 여유)

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

## 미결정 (추후 확장 시 논의)
- [ ] 장중 실시간 조회 지원 여부 (현재는 장 마감 후 배치만)
- [ ] `dollar_volume` 컬럼명 → `traded_value` 등으로 일반화 (한국에서 의미 어색)
- [ ] RS 공식을 블로그(best-n-optimal) 가중 합산 방식으로 개선 검토
