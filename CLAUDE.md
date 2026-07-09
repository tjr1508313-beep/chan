# 주식 스크리닝 프로젝트

## 프로젝트 개요
- 개인용 주식 스크리닝 웹 앱 (나만 사용)
- 목적: **상대강도(RS) 기반으로 지수 대비 강한 종목 찾기**
  - ⚠️ RS는 RSI가 아님. 지수 변화율 대비 종목 변화율을 비교하는 지표
- 스크리닝 대상: 미국주식(나스닥/S&P500) + 한국주식(코스피/코스닥) — **한 화면에 위/아래 표시**
  - 데이터 새로고침은 미국/한국 각각 **백그라운드 스레드**로 독립 실행
- 나중에 `매매일지` 폴더와 하나의 웹 앱으로 통합 예정 (사용자가 직접 통합)

## 공통 필터 조건 (종목 거르는 망)
1. **최소 주가**: 미국 $10 / 한국 1,000원
2. **최소 거래대금**: 미국 $20M / 한국 ₩300억 (하루 평균)
3. **최소 시가총액**: 미국 미적용 / **한국 3,000억 원**
4. **위험종목·관리종목 제외**
   - 미국: yfinance 메타 기반
   - 한국: **LS증권 OpenAPI** t1404/t1405 기반 (`screening/kr_risk.py`)
     - 제외(is_risk): 관리종목(t1404 jongchk=1) · 매매정지(t1405 jongchk=2) · 정리매매(t1405 jongchk=3)
     - 참고 배지만 (제외 X): 투자주의환기(t1404 j=4) · 투자경고(t1405 j=1) · 투자주의(t1405 j=4) · 단기과열(t1405 j=7)
     - 연속조회는 **응답 헤더 `tr_cont`="Y"/`tr_cont_key`** 로 페이지를 이어받음 (InBlock `cts_shcode` 단독은 같은 페이지 반복 → 누락)
     - LS 키(`LS_APP_KEY`/`LS_APP_SECRET`) 미설정·조회 실패 시 빈 dict → 기존 플래그 유지(graceful degrade). 클라우드/Actions에서 필터하려면 해당 환경 secrets에도 키 필요
     - ⚠️ 2026-06-15에 "t1404/t1405가 전체 리스트 반환"이라 잘못 결론내 FDR Dept로 갔으나, 실제로는 `jongchk` 파라미터 누락(시장구분 `gubun`과 혼동) 호출 버그였음. 2026-06-24 라이브로 카테고리별 정상 동작 재확인 → LS로 복귀
5. **중국기업 제외** (미국주식 한정)
6. **외국기업 제외** (한국주식 한정 — 모집단 단계 정적 제거)
7. **최근 20일 내 일일 변동폭 50% 이상 종목 제외**
8. **모집단 정적 제외** (한국주식 한정): 우선주 / 리츠 / ETF / 스팩
9. **최근 1~2일 급락 종목 제외**
   - D-0/D-1 일봉 종가 하락폭 ≥ 9일 ATR × **2.5배** 이면 제외
   - 사이드바 슬라이더(1.0~5.0)·체크박스로 조정/비활성 가능

## 섹터 분석 방향
- 목적: 주도섹터 안의 주도주를 찾기 위해 기존 RS 랭킹을 섹터 단위로 재집계
- 백엔드 기준: 강도 = 섹터 내부 `rs`(지수 대비) 상위 5종목 평균 / 폭 = `rs>0`(지수 이긴) 비율
- 섹터 정렬 = `0.7×강도_백분위 + 0.3×폭_백분위`(순위-백분위라 하락장에서도 순위 유지). 표시 숫자 = 지수 대비 강도(%p)
- 3종목 미만 섹터는 제외(`min_sector_size=3`)
- 함께 보는 지표: 섹터 종목 수, 양수 수익률 비율, 평균/중앙 RS, 섹터 1등 종목
- 섹터 메타가 없으면 `미분류`로 묶어 계산 흐름을 유지
- 미국은 yfinance sector 메타 활용
- 한국은 FDR 메타에 sector가 없어 `data/kr_sector_map.csv`의 `ticker,name_kr,sector,source,updated_at` 매핑을 우선 사용
  - `scripts/build_kr_sector_map.py`가 시총 상위 종목을 이름 규칙으로 분류해 1차 매핑 후보를 생성
  - `scripts/build_kr_sector_map_ls.py`가 LS증권 `t8424`/`t1516` 업종 API로 미분류 종목을 공식 업종명으로 보강
  - 현재 CSV는 name-rule 기반 초안이므로 틀린 섹터는 사용하면서 수동 보정
- LS증권 TR 코드/사용 예시는 `docs/ls-openapi-programgarden-reference.md`의 Programgarden Finance 참고 자료도 함께 확인
- Streamlit 화면은 각 자산군마다 상단 토글로 **`섹터별 보기`(기본) ↔ `전체 RS 보기`** 전환
  - 섹터별 보기 = 섹터-우선 주력 화면(스탁이지 "오늘의 업종" 스타일): 요약 지표카드 + **섹터 그리드(타일)**
    - 타일 = 강도 색(빨강 강세/파랑 약세). **타일 자체가 클릭 버튼** → 그 줄 아래로 섹터 종목이 펼쳐짐(별도 버튼 없음, 한 번에 하나)
    - **지수 대비 강도 상위 12개 섹터만 표시**(보기방식 라디오 옆 `전체 섹터 보기` 토글로 전체 노출). 펼침 → 그 섹터 종목 중 **코스피 20일 수익률 −5%p 이상(종목 절대수익률 기준, KR은 KOSPI=KS11 벤치마크) + 상위 10개**만 → 종목 클릭 시 5MA·9ATR 차트
      - ⚠️ 멤버 필터는 `rs`(각 시장 지수 대비)가 아니라 **절대수익률 vs 단일 코스피 벤치마크**로 한다. KQ11 지수가 망가지면 rs가 부풀려져 필터를 우회하기 때문(2026-06-24 코스닥 −23% 이상치 사례).
  - 섹터 정렬 = `0.7×강도_백분위 + 0.3×폭_백분위`. 강도 = 상위 5종목 `rs`(지수 대비) 평균, 폭 = `rs>0`(지수 이긴) 비율. 순위-백분위라 상승/하락장 모두 순위 일관.
  - **★ precompute & store (화면은 읽기만)**: 무거운 섹터 계산은 **새로고침 때 1회** 수행해 `sector_snapshot` 테이블에 저장(요약+멤버 전체). 화면은 `cache_load_sector_snapshot`로 **읽기만**(~0.01s). 계산 기준 고정(RS 20일, 거래대금 느슨 필터). 미저장 시 안내 + "지금 계산" 폴백 버튼.
    - 저장: `cache_save_sector_snapshot`/`cache_load_sector_snapshot`(`cache.py`). 굽기: `sector.screen_rebuild_sector_snapshot(market)` → 새로고침 경로 `refresh_cache.py`(`_refresh_us`/`_refresh_kr`) + 로컬 `_refresh_worker`에서 호출
    - scope: KR(코스피+코스닥 합산, 벤치마크 KS11) / US_^IXIC / US_^GSPC
  - **섹터용 느슨 필터**(저장 시 고정): KR 거래대금 100억↑·시총 3,000억↑ / US 거래대금 $10M↑·시총 $300M↑, 위험종목·우선주/ETF/스팩 제외 유지. 전체 RS 보기의 강한 필터와 별개.
    - **초저시총 급등주 왜곡 컷**: `exclude_caution=True`로 투자경고·투자주의·투자주의환기·단기과열 배지(`caution_flags` 비어있지 않음) 종목도 섹터 계산에서 제외. is_risk(관리/매매정지/정리매매)와 별개의 옵션 필터(`core.screen_apply_filters`, 기본 False). 시총 하한 부활과 함께 비금속 +136.95%(서산 등 초저시총 급등) 왜곡을 차단. ⚠️ 값 변경 후에는 **새로고침으로 sector_snapshot 재계산**해야 반영됨.
  - **한국 섹터는 코스피+코스닥 합산 계산(벤치마크는 KS11 단독)**: 모집단은 KS11+KQ11 종목을 합치되, 각 종목 rs는 **전부 KS11 대비**로 계산 → KQ11 지수를 벤치마크로 안 써서 이상치 왜곡 없음(단일 잣대). 코스닥 소부장 포함으로 반도체 등 그림이 완전해짐. rs가 곧 KS11 대비 초과수익. 미국은 단일 지수.
    - **되돌림 스위치** `sector.py`의 `_KR_SECTOR_INCLUDE_KOSDAQ`(기본 True). `False`로 바꾸고 **새로고침(sector_snapshot 재계산)** 하면 코스피(KS11) 단독으로 즉시 복귀. 코스피 단독 라이브 상태는 git tag `sector-kospi-only`로도 박제됨.
    - ⚠️ 단일 KS11 벤치마크라 코스닥 강세장에선 코스닥 종목이 rs 상위를 많이 차지할 수 있음(의도된 동작 — 실제로 지수를 이기면 리더로 인정). `screen_build_combined_sector_snapshot`(시장별 rs)는 코드에 남아있으나 KR 굽기 경로에서 미사용.
  - 구현: `screening/sector.py`(`_build_index_ranked`/`screen_build_combined_sector_snapshot`/`screen_rebuild_sector_snapshot`/`sector_snapshot_scope`), `screening/ui.py`(`_render_sector_view`/`_render_sector_detail`/`_render_sector_member_rows`/`_build_sector_tiles_css`/`_select_sector`/`ui_load_stored_sector_snapshot`), 색조 `_sector_tint`, CSS `theme.py` `_SECTOR_CSS`
- UI 밖에서도 `screening.sector.screen_build_sector_snapshot()` 또는
  `py scripts/show_sector_rs.py --index-code KS11 --period 20` 로 섹터 요약과 섹터 내부 주도주를 확인 가능
  - 특정 섹터만 볼 때는 `--sector 반도체` 옵션 사용
  - 한국은 기존 DB metadata의 sector가 비어 있어도 `data/kr_sector_map.csv`를 스냅샷 단계에서 덮어씌워 즉시 반영

## 개발 단계
> 상세 내역은 `.claude/plans/PLAN.md` 참고.

- **Phase 1** (미국주식 MVP) ✅ 완료
- **Phase 2** (한국주식 확장) ✅ 완료
- **Phase 3** (매매일지 통합) — 사용자 담당
- **섹터 RS 확장** — 섹터-우선 화면이 메인으로 승격됨(섹터별 보기 기본 + 전체 RS 보기 토글). 백엔드/CLI도 유지.

### 자동 갱신
GitHub Actions가 평일 캐시 DB를 자동 갱신 후 `data-cache` 브랜치에 push. 갱신 범위 = 지수 + 시세 + 메타(TTL 7일 증분) + 첫 화면 지수 차트 스냅샷.
로컬 앱 시작 시 `cache_sync.py`가 변경분만 자동 다운로드. 세팅: [docs/auto-refresh-setup.md](docs/auto-refresh-setup.md)

### 나무증권 관심종목 파일
- 로컬 앱: 프로젝트 폴더의 `02_*.csv`(US 나스닥) / `03_*.csv`(US S&P500) / `04_*.csv`(KR)를 직접 덮어씀
  - 미국 다운로드는 조회 지수(나스닥/S&P500)에 따라 그룹·파일명 자동 분기
- Streamlit Cloud: Google Apps Script를 통해 Google Drive 동기화 폴더의 CSV를 교체
- Drive 설정이 없거나 실패하면 기존 브라우저 다운로드 버튼 사용
- 설정: [docs/google-drive-watchlist-setup.md](docs/google-drive-watchlist-setup.md)

## 기술 스택
- Python / Streamlit
- 데이터 소스: 미국 = `yfinance`, 한국 = `FinanceDataReader`
- 차트: `streamlit-lightweight-charts-pro` (TradingView lightweight-charts 래퍼)
- SQLite 캐시 (`screening_cache.db`)
- 첫 화면 나스닥/코스피 카드: 카드 너비 안에 최근 110일 지수 캔들 차트 표시.
  배치 갱신 시 `index_chart_snapshot`을 미리 계산 (장 마감 후 갱신이므로 미완성 봉 없음).

## 에이전트 구성
- **스크리닝 백엔드** — RS 계산, 필터링 로직, 랭킹, 통계
- **스크리닝 프론트엔드** — Streamlit UI, 차트, 화면 구성
- **미국주식 데이터 API** — yfinance 등 외부 데이터 소스 연동 전담
- **한국주식 데이터 API** — FinanceDataReader 연동 전담

## 배포 환경 (중요 — 반드시 숙지)
- **이 앱은 Streamlit Cloud로 서비스 중** — GitHub 레포 `main` 브랜치를 직접 읽음
- **로컬 파일 수정만으로는 사이트에 반영 안 됨** → 반드시 GitHub에 push해야 자동 재배포
- **작업 완료 후 반드시**: `git commit` → `git push origin main` (또는 브랜치 → 머지 → push)
- `.bak` 파일, `_apply/` 폴더, `screening_cache.db*` 등 임시/캐시 파일은 커밋하지 말 것

## 작업 규칙
- **작업이 끝난 후 변경사항이 생기면** (기능 추가, 파일 추가, DB 변경, 필터 조건 변경 등) **이 파일을 자동으로 업데이트할 것**
- **에이전트 역할/담당 범위가 바뀌면** `.claude/agents/` 관련 파일도 업데이트할 것
- **계획이 변경되거나 Phase가 완료되면** `.claude/plans/PLAN.md` 도 업데이트할 것
- 대화 시작 시 메모리 파일(`MEMORY.md`)이 있다면 반드시 확인하고 관련 메모리 파일을 로드할 것
- 새 기능 추가 시 `/add-feature`, 버그 수정 시 `/fix-bug` 흐름 따를 것

## 스타일 규칙
- **라이트 테마**: 배경 `#f7f8fa`, 카드 `#ffffff`, 본문 `#1a1a1a`, 서브 `#6b7280`, 테두리 `#e5e7eb`
  - `.streamlit/config.toml` `base = "light"` 고정
- 한국/미국 주식: 수익 빨간색 (`#ff4b4b`), 손실 파란색 (`#1a9cff`) — 한국 주식 색상 체계
- **미국주식 + 한국주식을 한 화면에 위/아래로 표시** (사이드바에 두 자산군 설정이 함께 나열)

## 매매일지 프로젝트와의 관계
- 위치: `C:\테스트\` (매매일지) ↔ `C:\스크리닝\` (본 프로젝트)
- 현재는 **완전 독립**된 두 프로젝트
- 나중에 사용자가 직접 하나의 루트 폴더로 묶을 예정 → 통합 시 본 CLAUDE.md도 수정 필요

## 통합 대비 코딩 규칙 (반드시 준수)
매매일지 프로젝트와 나중에 병합할 때 충돌을 피하기 위한 사전 규칙.

### 1. 서브패키지 구조
스크리닝 로직은 모두 `screening/` 패키지 안에 넣는다. 진입점 `screening.py`는 껍데기만.
```
C:\스크리닝\
├── screening.py          # Streamlit 진입점 (통합 시 폐기)
└── screening/            # 로직 패키지 (통합 시 통째로 이동)
    ├── __init__.py
    ├── ui.py             # render_screening_page() 등 화면 렌더링 함수
    ├── core.py           # RS 계산, 필터링
    ├── data.py           # yfinance / FDR 호출
    ├── cache.py          # SQLite 캐시
    └── theme.py          # CSS/스타일 (함수로 감싸기)
```

### 2. session_state 네임스페이싱
모든 `st.session_state` 키는 **`scr_` 접두사** 필수.
- 예: `scr_selected_ticker`, `scr_rs_period`, `scr_filter_config`
- 미국: `scr_`, 한국: `scr_kr_` 접두사로 분리

### 3. st.set_page_config 위치
`screening.py` 진입점의 **`main()` 함수 안에서** 호출 (모듈 최상단 금지).

### 4. CSS 주입은 함수로 분리
`screening/theme.py`의 `apply_theme()` 함수로 감싸기. 통합 시 1회만 호출되도록.

### 5. 함수명 접두사 (캐시 충돌 예방)
`@st.cache_data` 로 캐시되는 함수는 **`us_` 접두사** 또는 **`screen_` 접두사**.
- 예: `us_load_prices(ticker)`, `screen_calc_rs(...)`

### 6. requirements.txt 버전 표기
`==` 고정 버전 대신 **`>=` 최소 버전** 사용 (병합 시 충돌 최소화).
