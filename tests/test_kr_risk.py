import screening.kr_risk as kr_risk


def test_classify_merges_designations():
    raw = {
        "관리": ["005930"],
        "거래정지": ["111111"],
        "정리매매": ["222222"],
        "투자경고": ["005930", "333333"],
        "투자주의": ["444444"],
        "단기과열": ["005930"],
    }
    out = kr_risk._classify(raw)
    assert out["005930"]["is_risk"] is True
    assert set(out["005930"]["labels"]) == {"관리", "투자경고", "단기과열"}
    assert out["111111"]["is_risk"] is True
    assert out["222222"]["is_risk"] is True
    assert out["333333"]["is_risk"] is False
    assert out["333333"]["labels"] == ["투자경고"]
    assert out["444444"]["is_risk"] is False


def test_fetch_returns_empty_without_keys(monkeypatch):
    monkeypatch.delenv("LS_APP_KEY", raising=False)
    monkeypatch.delenv("LS_APP_SECRET", raising=False)
    assert kr_risk.kr_fetch_risk_flags() == {}


def test_fetch_returns_empty_on_api_error(monkeypatch):
    monkeypatch.setenv("LS_APP_KEY", "k")
    monkeypatch.setenv("LS_APP_SECRET", "s")

    def boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(kr_risk, "_collect_raw_designations", boom)
    assert kr_risk.kr_fetch_risk_flags() == {}
