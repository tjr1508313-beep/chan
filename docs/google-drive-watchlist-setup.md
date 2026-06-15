# Google Drive 관심종목 자동 업데이트 설정

Streamlit Cloud의 버튼으로 나무증권 관심종목 CSV를 Google Drive에 덮어쓰고,
Google Drive 데스크톱 앱이 PC로 자동 동기화하도록 설정한다.

## 1. Drive 폴더 준비

1. Google Drive의 `내 드라이브`에 관심종목 전용 폴더를 만든다.
2. 폴더 URL의 마지막 ID를 기록한다.
3. Google Drive 데스크톱에서 해당 폴더가 PC에 동기화되는지 확인한다.

## 2. Apps Script 배포

1. [Google Apps Script](https://script.google.com/)에서 새 프로젝트를 만든다.
2. `docs/google-drive-watchlist-uploader.gs` 내용을 붙여넣는다.
3. 프로젝트 설정의 **스크립트 속성**에 아래 값을 추가한다.
   - `WATCHLIST_FOLDER_ID`: 1단계에서 기록한 폴더 ID
   - `WATCHLIST_UPLOAD_TOKEN`: 길고 임의적인 비밀 문자열
4. **배포 > 새 배포 > 웹 앱**을 선택한다.
   - 실행 사용자: 나
   - 액세스 권한: 모든 사용자
5. 배포 후 `/exec`로 끝나는 웹 앱 URL을 기록한다.

웹 앱은 토큰이 일치하고 파일명이 `02_*.csv` 또는 `04_*.csv`인 요청만 처리한다.

## 3. Streamlit Cloud Secrets

Streamlit Cloud의 **Manage app > Settings > Secrets**에 추가한다.

```toml
google_drive_upload_url = "https://script.google.com/macros/s/.../exec"
google_drive_upload_token = "WATCHLIST_UPLOAD_TOKEN과 같은 값"
```

설정 후 앱을 재부팅한다. Cloud 화면에는 Google Drive 업데이트 버튼과 수동 다운로드
버튼이 함께 표시된다.

## 4. 사용

1. Streamlit Cloud에서 `Google Drive 관심 종목 업데이트`를 누른다.
2. Google Drive 데스크톱이 PC의 동기화 폴더에 CSV를 반영할 때까지 기다린다.
3. 나무증권 HTS에서 동기화된 CSV를 가져온다.

로컬 앱의 `관심 종목 업데이트` 버튼은 기존처럼 프로젝트 폴더의 CSV를 직접 덮어쓴다.
