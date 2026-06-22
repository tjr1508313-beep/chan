import pandas as pd

from scripts import build_kr_sector_map as builder


def test_classify_name_uses_practical_sector_rules():
    assert builder._classify_name("삼성전자") == "반도체"
    assert builder._classify_name("HD현대일렉트릭") == "전력기기"
    assert builder._classify_name("알수없는회사") is None


def test_build_candidates_from_mocked_fdr(monkeypatch):
    listing = pd.DataFrame(
        [
            {"Code": "005930", "Name": "삼성전자", "Marcap": 1000, "ISU_CD": "KR7005930003", "Dept": ""},
            {"Code": "329180", "Name": "HD현대중공업", "Marcap": 800, "ISU_CD": "KR7329180004", "Dept": ""},
            {"Code": "000000", "Name": "알수없는회사", "Marcap": 700, "ISU_CD": "KR7000000000", "Dept": ""},
        ]
    )

    class _Fdr:
        @staticmethod
        def StockListing(market):
            return listing.copy()

    monkeypatch.setitem(__import__("sys").modules, "FinanceDataReader", _Fdr)

    candidates = builder.build_candidates(max_rows=10)

    assert list(candidates["ticker"]) == ["005930", "329180"]
    assert set(candidates["sector"]) == {"반도체", "조선"}
