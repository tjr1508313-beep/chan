/**
 * Streamlit Cloud에서 받은 나무증권 관심종목 CSV를 Google Drive에 저장한다.
 *
 * Apps Script 프로젝트 설정 > 스크립트 속성:
 * - WATCHLIST_FOLDER_ID: 저장할 Google Drive 폴더 ID
 * - WATCHLIST_UPLOAD_TOKEN: 충분히 긴 임의 문자열
 */
function doPost(e) {
  try {
    const props = PropertiesService.getScriptProperties();
    const expectedToken = props.getProperty("WATCHLIST_UPLOAD_TOKEN");
    const folderId = props.getProperty("WATCHLIST_FOLDER_ID");
    const body = JSON.parse(e.postData.contents);

    if (!expectedToken || body.token !== expectedToken) {
      return jsonResponse({ ok: false, error: "인증 토큰이 올바르지 않습니다." });
    }
    if (!folderId) {
      return jsonResponse({ ok: false, error: "WATCHLIST_FOLDER_ID가 설정되지 않았습니다." });
    }
    if (!/^0[1-9]_.+\.csv$/.test(body.filename || "")) {
      return jsonResponse({ ok: false, error: "허용되지 않은 파일명입니다." });
    }

    const folder = DriveApp.getFolderById(folderId);
    const bytes = Utilities.base64Decode(body.content_base64);
    const blob = Utilities.newBlob(bytes, "text/csv", body.filename);
    const files = folder.getFilesByName(body.filename);

    if (files.hasNext()) {
      // 기존 파일을 '같은 파일 ID 유지'한 채 내용만 교체한다(새 파일 안 생김).
      // DriveApp.setContent()는 문자열을 UTF-8로 재인코딩해 EUC-KR CSV를 깨뜨리므로,
      // Drive REST 미디어 업로드(PATCH)로 원본 바이트를 그대로 덮어써 인코딩을 보존한다.
      const fileId = files.next().getId();
      const resp = UrlFetchApp.fetch(
        "https://www.googleapis.com/upload/drive/v3/files/" + fileId + "?uploadType=media",
        {
          method: "patch",
          payload: blob,
          headers: { Authorization: "Bearer " + ScriptApp.getOAuthToken() },
          muteHttpExceptions: true,
        }
      );
      const code = resp.getResponseCode();
      if (code < 200 || code >= 300) {
        return jsonResponse({ ok: false, error: "내용 교체 실패(HTTP " + code + "): " + resp.getContentText() });
      }
      // 혹시 같은 이름의 중복 파일이 더 있으면 정리(휴지통)
      while (files.hasNext()) {
        files.next().setTrashed(true);
      }
      return jsonResponse({ ok: true, message: "기존 파일 내용 교체 완료: " + body.filename });
    }

    // 처음이면 새로 생성
    folder.createFile(blob);
    return jsonResponse({ ok: true, message: "새 파일 생성 완료: " + body.filename });
  } catch (error) {
    return jsonResponse({ ok: false, error: String(error) });
  }
}

function jsonResponse(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * 최초 1회: 편집기에서 이 함수를 선택해 ▶ 실행하면 권한 승인 창이 뜬다.
 * UrlFetchApp(외부 요청)·Drive 권한을 한꺼번에 승인해 doPost 가 동작하게 한다.
 * 승인 후에는 다시 실행할 필요 없다.
 */
function authorize() {
  DriveApp.getRootFolder();  // Drive 권한 트리거
  const resp = UrlFetchApp.fetch(
    "https://www.googleapis.com/drive/v3/about?fields=user",
    {
      headers: { Authorization: "Bearer " + ScriptApp.getOAuthToken() },
      muteHttpExceptions: true,
    }
  );  // 외부 요청(script.external_request) 권한 트리거
  Logger.log("authorize OK: HTTP " + resp.getResponseCode());
}
