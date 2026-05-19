# Streamlit Community Cloud 배포 가이드

내 컴퓨터가 꺼져있어도 URL 만 알면 접속 가능한 웹사이트로 만든다.
무료, GitHub 연동, 자동 재배포.

## 사전 준비 (이미 충족됨)
- ✅ GitHub 레포: `tjr1508313-beep/chan`
- ✅ 진입점: `screening.py`
- ✅ `requirements.txt`
- ✅ GitHub Actions 가 `data-cache` 브랜치에 캐시 자동 push
- ✅ `cache_sync.py` 가 앱 시작 시 캐시 자동 다운로드

## 1단계 — Streamlit Cloud 가입
1. https://share.streamlit.io 접속
2. **Continue with GitHub** 클릭 → `tjr1508313-beep` 계정으로 로그인
3. Streamlit 에 GitHub 접근 권한 허용

## 2단계 — 앱 생성
1. 대시보드 우상단 **Create app** 클릭
2. **Deploy a public app from GitHub** 선택
3. 입력:
   - **Repository**: `tjr1508313-beep/chan`
   - **Branch**: `main`
   - **Main file path**: `screening.py`
   - **App URL (선택)**: 예) `chan-screening` → `https://chan-screening.streamlit.app`

## 3단계 — Secrets 등록 (중요)
**Advanced settings → Secrets** 에 아래 내용 붙여넣기:

```toml
app_password = "원하는_비밀번호"
```

- `app_password`: 웹 공개되므로 **반드시 설정**. 미설정 시 누구나 접속 가능
- `github_cache_token` 은 레포가 public 이면 불필요 (인증 없이 raw URL 직접 접근)

## 4단계 — Deploy
**Deploy!** 버튼 클릭 → 2~5분 후 URL 활성화.

첫 빌드 시 `requirements.txt` 의 모든 패키지 설치 (yfinance, FDR, lightweight-charts 등).
로그는 우하단 **Manage app** 에서 실시간 확인 가능.

## 운영 팁

### 슬립 모드
- 7일간 트래픽 없으면 슬립 → 다시 접속 시 30초~1분 깨어나는 시간
- 깨어난 후엔 정상. 매일 한 번씩 접속하면 슬립 안 걸림

### 자동 재배포
- `main` 브랜치에 push 하면 Streamlit 이 감지 → 자동 재빌드
- 코드만 수정하면 끝, 별도 배포 명령 불필요

### 데이터 갱신
- 내 컴퓨터와 무관, GitHub Actions 가 알아서 갱신
- KR: 평일 KST 15:40 / 16:10 / 16:40
- US: 평일 KST 07:00 / 07:30 / 08:00
- Cloud 앱은 `cache_sync.py` 가 시작 시 최신 `screening_cache.db.gz` 다운로드

### 리소스 제한 (무료 티어)
- 메모리 1GB, CPU 공유
- 캐시 DB 가 큰 편이지만 gzip 압축 (~41MB) 이라 문제 없음
- 동시 접속 부담은 개인 사용이라 신경 안 써도 됨

### 문제 발생 시
- **Manage app → Logs**: 실시간 stderr/stdout 확인
- **Reboot app**: 강제 재시작
- 패키지 충돌 시 `requirements.txt` 수정 후 push → 자동 재빌드

## 보안 체크리스트
- [x] `secrets.toml` 은 `.gitignore` 처리되어 GitHub 에 안 올라감
- [ ] `app_password` 강한 값으로 설정
- [x] `github_cache_token` 불필요 (public 레포)
