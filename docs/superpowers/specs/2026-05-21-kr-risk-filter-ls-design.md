# 한국 관리종목 필터 — LS증권 OpenAPI 데이터 소스 설계

*작성일: 2026-05-21*

## 목표

한국주식 RS 스크리닝에서 **관리종목 / 거래정지·정리매매** 종목을 자동 제외하고,
**투자경고 / 투자주의 / 단기과열** 지정은 제외하지 않고 "참고 배지"로만 표시한다.
데이터 소스는 **LS증권 REST OpenAPI**.

기존 보류 사유(KRX 공시 익명 차단, pykrx 미지원)를 LS증권 계좌 기반 인증 API로 해소한다.

## 배경 — 기존 인프라

필터 파이프라인은 이미 전부 깔려 있고, 빈 곳은 한국 종목에 `is_risk=True`를 세팅하는
**데이터 소스뿐**이다.

- `cache.py`: `metadata` 테이블에 `is_risk` 컬럼 존재, 저장/조회 경로 완비
- `core.py:343` `exclude_risk` 필터: `is_risk==True` 종목 제외 (NaN/None은 보수적 통과)
- `ui.py:440` `exclude_risk` 체크박스 노출
- `data_kr.py:254` `kr_get_meta()`가 현재 `is_risk: False` 하드코딩 ← 교체 대상

## 결정 사항

| 항목 | 결정 |
|------|------|
| 데이터 소스 | LS증권 REST OpenAPI |
| 제외 대상 (`is_risk=True`) | 관리종목, 거래정지/정리매매 |
| 참고 배지만 (제외 X) | 투자경고, 투자주의, 단기과열 |
| 실행 위치 | 로컬 + GitHub Actions 둘 다 |
| 키 권한 | **조회전용** (주문권한 없음) — 유출 시 시세 조회만 가능 |
| 키 저장 | 로컬 `secrets.toml`/env, 클라우드 GitHub Secrets(암호화) |
| 갱신 주기 | 매 새로고침마다 (시장경보·단기과열은 매일 변동 — 7일 메타 TTL과 분리) |

## 아키텍처

### 1. 신규 모듈 `screening/kr_risk.py`

순수 파이썬 (streamlit import 금지). LS OpenAPI 클라이언트.

```python
def kr_fetch_risk_flags() -> dict[str, dict]:
    """LS OpenAPI로 관리/거래정지/시장경보 지정 종목 조회.

    Returns:
        { "005930": {"is_risk": True, "labels": ["관리"]},
          "123450": {"is_risk": False, "labels": ["투자경고", "단기과열"]} }
        - is_risk=True  ⟸ 관리종목 OR 거래정지/정리매매
        - labels        = 표시용 전체 지정 텍스트
        LS 키 미설정/API 실패 시 빈 dict + 경고 로그 (graceful degrade)
    """
```

- 토큰: `POST /oauth2/token` (grant_type=client_credentials, App Key/Secret).
  ~1일 유효, 프로세스 내 캐시
- 지정 종류별 리스트 TR 호출 (구 xingAPI `t1404` 관리/불성실/투자유의,
  `t1405` 락/거래정지/시장경보 계열 — **정확한 tr_cd는 구현 시 라이브 테스트베드로 확정**)
- 시크릿: `kr_risk`는 **`os.environ`만** 읽는다 (streamlit 비의존 유지).
  - GitHub Actions: 워크플로우 `env`로 주입 (아래 6번)
  - 로컬: 앱 진입점(`screening.py`)이 `st.secrets`의 `ls_app_key`/`ls_app_secret`을
    `os.environ`에 1회 복사 (없으면 미설정 → graceful degrade). 직접 env 설정도 가능
- 외부 의존: `requests` 우선, 없으면 `urllib` 폴백 (기존 `cache_sync.py` 정책 일치)

### 2. 캐시 (`cache.py`)

- `metadata` 테이블에 컬럼 추가: `caution_flags TEXT` (참고 라벨 콤마조인,
  예 `"투자경고,단기과열"`). `is_risk`는 기존 컬럼 재사용
- `_migrate_caution_flags_column()` — `_migrate_dollar_volume_column()` 패턴 그대로.
  `init_cache()`에서 PRAGMA 검사 후 없으면 `ALTER TABLE ... ADD COLUMN`.
  원격 동기화로 들어온 구 DB도 자동 처리
- 신규 `update_risk_flags(flags: dict) -> None` — 메타 TTL과 **무관하게**
  `is_risk`/`caution_flags` 두 컬럼만 갱신. flags에 없는 코드는 두 컬럼 클리어
  (지정 해제 반영). metadata 행이 없는 코드는 skip (메타 갱신이 행 생성 담당)

### 3. 코어 (`core.py`)

- `exclude_risk` 필터: **변경 없음** (`is_risk==True` 제외)
- `_SCREEN_DF_COLUMNS`에 `caution_flags` 추가, `screen_build_screening_df`에서
  meta로부터 채움 (필터엔 미사용, 표시 전용)

### 4. 배치 (`batch_kr.py`)

- 시세 갱신 후 `kr_fetch_risk_flags()` 1회 호출 → `cache.update_risk_flags(flags)`
- 메타 TTL(7일) 스킵 여부와 무관하게 매 실행 시 플래그 패스 수행
- LS 호출 실패해도 배치 전체는 정상 완료

### 5. UI (`ui.py`)

- 랭킹 테이블: 종목명 옆 참고 배지 (예: `투경`·`과열` 태그) — 기존 "5일선 이탈
  배지" 패턴 재사용
- `exclude_risk` 체크박스 라벨/툴팁: "관리종목·거래정지/정리매매 제외
  (LS증권 데이터)" + 참고 지정은 제외하지 않음 명시
- 미국 쪽 무변경 (`caution_flags` 빈 값)

### 6. 자동 갱신 / 시크릿

- 로컬: `.streamlit/secrets.toml`의 `ls_app_key`/`ls_app_secret` 또는
  env `LS_APP_KEY`/`LS_APP_SECRET`
- `refresh-kr.yml`: `env`로 `LS_APP_KEY: ${{ secrets.LS_APP_KEY }}`,
  `LS_APP_SECRET: ${{ secrets.LS_APP_SECRET }}` 주입
- `docs/auto-refresh-setup.md`, `CLAUDE.md`, `.claude/plans/PLAN.md` 갱신

## 데이터 흐름

```
batch_kr (로컬 / GitHub Actions)
  └─ 시세·메타 갱신 (기존)
  └─ kr_fetch_risk_flags()  ── LS OpenAPI ──▶ {code: {is_risk, labels}}
        └─ cache.update_risk_flags()  ──▶ metadata.is_risk / caution_flags
                                              │
앱 실행 ── core.screen_build_screening_df ──┘ (meta 읽어 df 구성)
        └─ exclude_risk 필터: is_risk 제외
        └─ caution_flags: UI 배지 표시
```

## 에러 처리

- LS 키 미설정 또는 API 실패 → 경고 로그, 플래그 미변경, 갱신 정상 완료
- `is_risk` NaN/None은 기존대로 보수적 통과 (필터 누수 < 오탈락 방지)
- 토큰 만료/401 → 1회 재발급 후 재시도, 그래도 실패면 graceful degrade

## 테스트

- `kr_risk`: mocked TR 응답 → is_risk/labels 분류 정확성, 키 미설정 시 빈 dict
- `cache`: `_migrate_caution_flags_column` 구 스키마 ALTER, `update_risk_flags`
  갱신 + 미포함 코드 클리어
- `core`: `exclude_risk`가 `is_risk=True` 종목 제외, `caution_flags`가 df에 전달
- UI: 참고 배지 렌더 스모크

## 사용자 1회 세팅 (잔여)

1. LS증권 계좌 + OpenAPI 앱 등록 → **조회전용** App Key/Secret 발급
2. 로컬 `.streamlit/secrets.toml`에 키 입력
3. GitHub 레포 Settings → Secrets에 `LS_APP_KEY`, `LS_APP_SECRET` 등록

## 범위 외 (YAGNI)

- 미국주식 caution 배지 (해당 없음)
- 실시간 장중 관리종목 조회 (배치 기반 유지)
- LS API 주문/계좌 기능 (조회만)
