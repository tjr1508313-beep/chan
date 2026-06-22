import pandas as pd

import screening.data_kr as data_kr


def test_kr_get_sector_reads_csv_mapping(tmp_path, monkeypatch):
    csv_path = tmp_path / "kr_sector_map.csv"
    csv_path.write_text(
        "ticker,name_kr,sector,source,updated_at\n"
        "005930,삼성전자,반도체,manual,2026-06-22\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(data_kr, "_KR_SECTOR_CSV", csv_path)
    data_kr._load_kr_sector_map.cache_clear()

    assert data_kr.kr_get_sector("5930") == "반도체"


def test_kr_get_meta_includes_sector_mapping(tmp_path, monkeypatch):
    csv_path = tmp_path / "kr_sector_map.csv"
    csv_path.write_text(
        "ticker,name_kr,sector,source,updated_at\n"
        "000660,SK하이닉스,반도체,manual,2026-06-22\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(data_kr, "_KR_SECTOR_CSV", csv_path)
    data_kr._load_kr_sector_map.cache_clear()
    monkeypatch.setattr(
        data_kr,
        "_row_for_ticker",
        lambda ticker: pd.Series(
            {
                "Name": "SK하이닉스",
                "Marcap": 1000.0,
                "_market": "KOSPI",
            }
        ),
    )

    meta = data_kr.kr_get_meta("000660")

    assert meta["sector"] == "반도체"
    assert meta["name_kr"] == "SK하이닉스"
