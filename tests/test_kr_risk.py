import pandas as pd
import screening.kr_risk as kr_risk


def test_fetch_returns_empty_on_fdr_error(monkeypatch):
    """FDR 조회 실패 시 빈 dict 반환 (graceful degrade)."""
    import FinanceDataReader as fdr

    def boom(market):
        raise RuntimeError("network down")

    monkeypatch.setattr(fdr, "StockListing", boom)
    assert kr_risk.kr_fetch_risk_flags() == {}


def test_fetch_classifies_dept_correctly(monkeypatch):
    """Dept 컬럼 값에 따라 is_risk / labels 분류가 올바른지 확인."""
    import FinanceDataReader as fdr

    mock_df = pd.DataFrame([
        {"Code": "000020", "Dept": "관리종목(소속부없음)"},
        {"Code": "005930", "Dept": ""},                     # 정상 종목 → 제외
        {"Code": "123456", "Dept": "투자주의환기종목(소속부없음)"},
        {"Code": "999999", "Dept": "우량기업부"},            # 정상 KOSDAQ → 제외
    ])
    monkeypatch.setattr(fdr, "StockListing", lambda market: mock_df)

    result = kr_risk.kr_fetch_risk_flags()

    assert "000020" in result
    assert result["000020"]["is_risk"] is True
    assert "관리종목" in result["000020"]["labels"]

    assert "123456" in result
    assert result["123456"]["is_risk"] is False
    assert "투자주의환기" in result["123456"]["labels"]

    assert "005930" not in result
    assert "999999" not in result
