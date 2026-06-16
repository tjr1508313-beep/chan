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
   - 한국: **LS증권 OpenAPI** (관리종목·거래정지·정리매매 제외 / 투자경고·투자주의·단기과열은 참고 배지)
5. **중국기업 제외** (미국주식 한정)
6. **외국기업 제외** (한국주식 한정 — 모집단 단계 정적 제거)
7. **최근 20일 내 일일 변동폭 50% 이상 종목 제외**
8. **모집단 정적 제외** (한국주식 한정): 우선주 / 리츠 / ETF / 스팩
9. **최근 1~2일 급락 종목 제외**
   - D-0/D-1 일봉 종가 하락폭 ≥ 9일 ATR × **2.5배** 이면 제외
   - 사이드바 슬라이더(1.0~5.0)·체크박스로 조정/비활성 가능

## 개발 단계
> 상세 내역은 `.claude/plans/PLAN.md` 참고.

- **Phase 1** (미국주식 MVP) ✅ 완료
- **Phase 2** (한국주식 확장) ✅ 완료
- **Phase 3** (매매일지 통합) — 사용자 담당

### 자동 갱신
GitHub Actions가 평일 캐시 DB를 자동 갱신 후 `data-cache` 브랜치에 push. 갱신 범위 = 지수 + 시세 + 메타(TTL 7일 증분) + 첫 화면 지수 차트 스냅샷.
로컬 앱 시작 시 `cache_sync.py`가 변경분만 자동 다운로드. 세팅: [docs/auto-refresh-setup.md](docs/auto-refresh-setup.md)

### 나무증권 관심종목 파일
- 로컬 앱: 프로젝트 폴더의 `02_*.csv` / `04_*.csv`를 직접 덮어씀
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
