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
3. **프로젝트 설정(⚙️) > "appsscript.json 매니페스트 파일을 편집기에 표시" 체크** 후,
   편집기의 `appsscript.json` 을 `docs/google-drive-watchlist-appsscript.json` 내용으로 교체한다.
   - 핵심: `oauthScopes` 에 `drive` + `script.external_request` 가 들어가야
     in-place 파일 교체용 `UrlFetchApp` 호출 권한이 승인된다.
     (이게 없으면 "permission to call UrlFetchApp.fetch" 에러)
4. 프로젝트 설정의 **스크립트 속성**에 아래 값을 추가한다.
   - `WATCHLIST_FOLDER_ID`: 1단계에서 기록한 폴더 ID
   - `WATCHLIST_UPLOAD_TOKEN`: 길고 임의적인 비밀 문자열
5. 편집기 함수 드롭다운에서 **`authorize` 선택 후 ▶ 실행** → 권한 검토에서
   **외부 서비스 연결 포함** 전체 허용. (로그에 `authorize OK` 뜨면 성공)
6. **배포 > 새 배포 > 웹 앱**을 선택한다.
   - 실행 사용자: 나
   - 액세스 권한: 모든 사용자
7. 배포 후 `/exec`로 끝나는 웹 앱 URL을 기록한다.

웹 앱은 토큰이 일치하고 파일명이 `0N_*.csv`(01~09) 형식인 요청만 처리한다.
현재 사용: `02_나스닥 rs.csv`(US 나스닥) / `03_s&p rs.csv`(US S&P500) / `04_rs탑20.csv`(KR).

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
