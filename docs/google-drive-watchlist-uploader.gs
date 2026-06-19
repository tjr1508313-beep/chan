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

    // setContent()는 문자열을 UTF-8로 다시 인코딩해 EUC-KR CSV를 깨뜨릴 수 있다.
    // 기존 동명 파일을 휴지통으로 이동한 뒤 원본 바이트 blob으로 교체한다.
    while (files.hasNext()) {
      files.next().setTrashed(true);
    }
    folder.createFile(blob);

    return jsonResponse({ ok: true, message: "Google Drive 업데이트 완료: " + body.filename });
  } catch (error) {
    return jsonResponse({ ok: false, error: String(error) });
  }
}

function jsonResponse(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}
