import base64
import json

import screening.drive_upload as drive_upload


class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


def test_drive_upload_configured_from_explicit_values():
    assert drive_upload.drive_upload_configured("https://example.test/upload", "secret")
    assert not drive_upload.drive_upload_configured("", "")


def test_upload_watchlist_sends_base64_payload(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"ok": True, "message": "updated"})

    monkeypatch.setattr(drive_upload, "urlopen", fake_urlopen)
    result = drive_upload.upload_watchlist_to_drive(
        "04_rs탑20.csv",
        b"watchlist",
        endpoint="https://example.test/upload",
        token="secret",
    )

    assert result.ok is True
    assert result.message == "updated"
    assert captured["payload"]["token"] == "secret"
    assert captured["payload"]["filename"] == "04_rs탑20.csv"
    assert base64.b64decode(captured["payload"]["content_base64"]) == b"watchlist"


def test_upload_watchlist_rejects_missing_or_insecure_config():
    missing = drive_upload.upload_watchlist_to_drive("x.csv", b"x")
    insecure = drive_upload.upload_watchlist_to_drive(
        "x.csv", b"x", endpoint="http://example.test", token="secret"
    )

    assert missing.ok is False
    assert insecure.ok is False
