"""Google Drive Apps Script를 통한 관심종목 파일 업로드."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class DriveUploadResult:
    ok: bool
    message: str


def drive_upload_configured(endpoint: str = "", token: str = "") -> bool:
    """명시 인자 또는 환경변수에 업로드 설정이 모두 있는지 확인."""
    url = endpoint.strip() or os.environ.get("GOOGLE_DRIVE_UPLOAD_URL", "").strip()
    secret = token.strip() or os.environ.get("GOOGLE_DRIVE_UPLOAD_TOKEN", "").strip()
    return bool(url and secret)


def upload_watchlist_to_drive(
    filename: str,
    content: bytes,
    *,
    endpoint: str = "",
    token: str = "",
    timeout: int = 20,
) -> DriveUploadResult:
    """Apps Script 웹 앱으로 CSV를 보내 같은 이름의 Drive 파일을 덮어쓴다."""
    url = endpoint.strip() or os.environ.get("GOOGLE_DRIVE_UPLOAD_URL", "").strip()
    secret = token.strip() or os.environ.get("GOOGLE_DRIVE_UPLOAD_TOKEN", "").strip()
    if not url or not secret:
        return DriveUploadResult(False, "Google Drive 업로드 설정이 없습니다.")
    if not url.startswith("https://"):
        return DriveUploadResult(False, "Google Drive 업로드 URL은 https:// 주소여야 합니다.")

    payload = json.dumps(
        {
            "token": secret,
            "filename": filename,
            "content_base64": base64.b64encode(content).decode("ascii"),
        }
    ).encode("utf-8")
    request = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
        result = json.loads(body)
    except Exception as exc:
        return DriveUploadResult(False, f"Google Drive 업로드 실패: {exc}")

    if result.get("ok") is True:
        return DriveUploadResult(True, str(result.get("message") or "Google Drive 업데이트 완료"))
    return DriveUploadResult(False, str(result.get("error") or "Google Drive 업로드에 실패했습니다."))
