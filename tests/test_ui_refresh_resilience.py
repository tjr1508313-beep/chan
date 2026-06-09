"""구성종목 소스 갱신 실패 시 앱이 크래시하지 않고 우아하게 폴백하는지 검증.

배경: Streamlit Cloud(해외 IP)에서 fdr.StockListing 이 KRX(data.krx.co.kr)
차단으로 ValueError 를 던진다. 이 예외가 메인 스레드의 _start_refresh 에서
잡히지 않으면 render_screening_page 전체가 죽는다.
"""

import screening.ui as ui


_SPEC = {"key_prefix": "scr_kr", "normalize_upper": False}


def _patch_session_state(monkeypatch):
    fake: dict = {}
    monkeypatch.setattr(ui.st, "session_state", fake)
    return fake


def _boom(index_code):
    raise ValueError("Failed to load data from http://data.krx.co.kr/comm/...")


def test_start_refresh_no_crash_when_source_and_cache_fail(monkeypatch):
    """소스 실패 + 캐시도 비어 있으면 예외 전파 없이 '실패' 잡만 기록."""
    fake = _patch_session_state(monkeypatch)
    monkeypatch.setattr(ui, "ui_refresh_index_universe", _boom)
    monkeypatch.setattr(ui, "cache_load_universe", lambda code: [])

    # 예외가 전파되면(=현재 버그) 이 호출이 raise 하여 테스트 실패한다.
    ui._start_refresh(_SPEC, "KS11", force=False)

    job = fake["scr_kr_refresh_job"]
    assert job["running"] is False
    assert job["phase"] == "실패"
    assert "data.krx.co.kr" in job["error"]


def test_start_refresh_falls_back_to_cached_universe(monkeypatch):
    """소스가 터져도 캐시에 유니버스가 있으면 폴백해 시세/메타 갱신 잡을 시작."""
    fake = _patch_session_state(monkeypatch)
    monkeypatch.setattr(ui, "ui_refresh_index_universe", _boom)
    monkeypatch.setattr(ui, "cache_load_universe", lambda code: ["005930", "000660"])
    monkeypatch.setattr(
        ui, "_sort_tickers_stale_first", lambda t, normalize_upper: list(t)
    )

    started: dict = {}

    class _FakeThread:
        def __init__(self, *a, **k):
            started["created"] = True

        def start(self):
            started["started"] = True

    monkeypatch.setattr(ui.threading, "Thread", _FakeThread)

    ui._start_refresh(_SPEC, "KS11", force=False)

    job = fake["scr_kr_refresh_job"]
    assert job["running"] is True
    assert job["px_total"] == 2
    assert started.get("started") is True
    # 폴백 사실이 사용자 메시지에 남아야 함
    assert any("캐시" in m for m in job["messages"])
