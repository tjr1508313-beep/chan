# 자동 갱신 (GitHub Actions) 세팅 가이드

평일 장 종료 후 캐시 DB 가 GitHub Actions 에서 자동 갱신되어, 로컬에서 앱을
열면 즉시 최신 데이터로 시작되는 흐름.

## 동작 요약

```
GitHub Actions  (월~금)
   KR  15:40 KST  →  scripts/refresh_cache.py --market kr
   US  07:00 KST  →  scripts/refresh_cache.py --market us
        ↓
   data-cache 브랜치(orphan)에 screening_cache.db, last_updated.txt 강제 푸시
        ↓
로컬 PC: 앱 시작 시 cache_sync 가 자동으로 data-cache 의 stamp 확인
   → 로컬 < 원격 이면 DB 다운로드 후 교체
   → 사이드바에 "자동 갱신: 최신 / 마지막: YYYY-MM-DD HH:MM KST" 배지
```

실패 시 텔레그램으로 알림 (성공은 조용).

## 1회만 하면 되는 세팅

### 1. GitHub Secrets 등록

레포 `Settings → Secrets and variables → Actions → New repository secret`:

| 이름 | 값 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather 에서 발급한 봇 토큰 (`123456:ABC...`) |
| `TELEGRAM_CHAT_ID` | 알림을 받을 채팅 ID (개인 채팅이면 본인 user_id, 그룹이면 `-` 시작 음수) |

> chat_id 모르겠으면 `@userinfobot` 에게 메시지 보내면 알려줌.

### 2. data-cache 브랜치 부트스트랩 (선택)

브랜치는 첫 워크플로우가 자동 생성한다. 다만 첫 실행은 캐시가 없어 처음부터 받느라
오래 걸린다 (US 15~25분, KR 4~6분). 기존 로컬 DB 가 있으면 미리 푸시해 시간 단축
가능:

```powershell
# 현재 로컬 캐시를 data-cache 브랜치 초기값으로 푸시
git checkout --orphan data-cache
git rm -rf --cached . 
"$(Get-Date -AsUTC -Format o)" | Out-File -Encoding utf8 last_updated.txt
"market=manual" | Add-Content -Encoding utf8 last_updated.txt
git add screening_cache.db last_updated.txt
git commit -m "initial cache snapshot"
git push --force origin data-cache
git checkout main
```

### 3. (옵션) 첫 실행 수동 트리거

레포 `Actions` 탭 → `Refresh US cache` / `Refresh KR cache` → `Run workflow` 로
즉시 한번 돌릴 수 있음. 시각이 맞을 때까지 기다리지 않아도 됨.

## 일정 (cron, UTC 기준)

| Workflow | cron | KST |
|---|---|---|
| `refresh-kr.yml` | `40 6 * * 1-5` | 평일 15:40 |
| `refresh-us.yml` | `0 22 * * 0-4` | 평일 07:00 (UTC 일~목 = KST 월~금) |

> ⚠️ GitHub Actions cron 은 정확한 시각 보장 X — 최대 ~15 분 지연 가능. 시세는
> 그 정도 늦게 받아도 무방하지만, 더 빨리 받고 싶으면 cron 을 앞당기지 말고
> Actions 탭에서 수동 트리거.

## 갱신 범위 (사용자 결정)

- ✅ 지수 시세 (`^IXIC`, `^GSPC`, `KS11`, `KQ11`)
- ✅ 구성종목 시세 (NASDAQ + S&P500 / KOSPI + KOSDAQ)
- ❌ **메타데이터(시총·이름·섹터·중국기업 여부) 제외**

메타는 7일 TTL 이고 자주 변하지 않아 자동 갱신에서 빠짐. 분기에 한 번 정도
앱 사이드바의 `yfinance/FDR 에서 내려받기` 버튼으로 수동 갱신.

## 환경변수로 끄기 / 다른 레포 가리키기

```powershell
# 자동 동기화 끄기 (로컬에서 자체 DB 만 쓰고 싶을 때)
$env:SCREENING_SKIP_REMOTE_SYNC = "1"

# 다른 GitHub 레포의 캐시를 받게 변경
$env:SCREENING_CACHE_REPO = "owner/repo"
```

## Private 레포일 때 — PAT(Personal Access Token) 세팅

Private 레포의 raw URL 은 비인증 호출 불가 → 로컬 앱이 401/404 받음.
PAT 를 발급해 로컬에 저장하면 인증된 다운로드로 동작.

### 1) PAT 발급 (Fine-grained 권장, 5분)

1. https://github.com/settings/personal-access-tokens/new 열기
2. **Token name**: `screening-cache-readonly` 같은 식별 가능한 이름
3. **Expiration**: 1년 (만료 후 재발급 — 만료 알림 옴)
4. **Repository access**: `Only select repositories` → 본인 스크리닝 레포 (`tjr1508313-beep/chan`) 만 선택
5. **Repository permissions**: 아래로 스크롤 → **`Contents`** 항목을 **`Read-only`** 로
   - 다른 권한은 모두 `No access` 유지 — 토큰이 유출돼도 캐시 다운로드 외엔 못 함
6. `Generate token` → 표시된 토큰 (`github_pat_...`) 을 **즉시 복사** (다시 못 봄)

> Classic PAT 도 동작하지만 권한 범위가 넓어 권장하지 않음.

### 2) 로컬에 토큰 저장 (둘 중 하나)

**A. `.streamlit/secrets.toml` (권장)**

```toml
# C:\스크리닝\.streamlit\secrets.toml
github_cache_token = "github_pat_여기에_붙여넣기"
```

> 이 파일은 `.gitignore` 에 이미 등록 → 절대 git 에 안 올라감.

**B. 환경변수**

```powershell
# 영구 설정 (재부팅 후에도 유지)
setx SCREENING_CACHE_TOKEN "github_pat_여기에_붙여넣기"

# 임시 (현재 PowerShell 세션만)
$env:SCREENING_CACHE_TOKEN = "github_pat_여기에_붙여넣기"
```

A 와 B 둘 다 설정돼 있으면 **B(환경변수) 가 우선**.

### 3) 앱 재시작

기존 Streamlit 프로세스 종료(Ctrl+C) → `streamlit run screening.py` 다시 실행.
사이드바 상단에 "자동 갱신: 방금 동기화" 떠야 정상.

### 토큰 만료 후

만료 7일 전 GitHub 이메일 알림 → 같은 페이지에서 `Regenerate token` 으로 갱신
→ 로컬 토큰만 새 값으로 교체 (다른 변경 불필요).

### 토큰이 유출됐다고 의심되면

GitHub Settings → Personal access tokens → 해당 토큰 `Revoke` 1초.
권한이 `Contents: Read-only` 뿐이므로 다른 데이터엔 영향 0.

## 문제 진단

- **앱 사이드바에 "원격 캐시 없음"** → `data-cache` 브랜치가 아직 안 만들어짐.
  Actions 탭에서 수동 트리거 1회.
- **"동기화 실패"** → 네트워크 / 레포 비공개 시 raw URL 접근 불가. 레포 public
  으로 두거나, 토큰 인증 방식으로 변경 필요 (현재는 비인증 raw URL 사용).
- **텔레그램 알림이 안 옴** → Secrets 두 개가 모두 입력됐는지, 봇이 본인과의
  채팅 첫 메시지를 한 번 받았는지 확인.
- **DB 가 너무 크다는 푸시 에러** → 30MB 까지는 raw 다운로드 제한 안에 들어옴.
  100MB 넘어가면 git LFS 또는 Release Asset 방식으로 전환 필요.
