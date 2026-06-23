import pandas as pd

from scripts.build_kr_sector_map_ls import merge_sector_maps


def test_merge_sector_maps_preserves_existing_by_default():
    existing = pd.DataFrame(
        [
            {
                "ticker": "000660",
                "name_kr": "SK하이닉스",
                "sector": "반도체",
                "source": "manual",
                "updated_at": "2026-06-22",
            }
        ]
    )
    candidates = pd.DataFrame(
        [
            {
                "ticker": "000660",
                "name_kr": "SK하이닉스",
                "sector": "전기 전자",
                "source": "ls-industry",
                "updated_at": "2026-06-23",
            },
            {
                "ticker": "005930",
                "name_kr": "삼성전자",
                "sector": "전기 전자",
                "source": "ls-industry",
                "updated_at": "2026-06-23",
            },
        ]
    )

    merged = merge_sector_maps(existing, candidates)

    sectors = merged.set_index("ticker")["sector"].to_dict()
    assert sectors["000660"] == "반도체"
    assert sectors["005930"] == "전기 전자"


def test_merge_sector_maps_can_overwrite_existing():
    existing = pd.DataFrame(
        [
            {
                "ticker": "000660",
                "name_kr": "SK하이닉스",
                "sector": "반도체",
                "source": "manual",
                "updated_at": "2026-06-22",
            }
        ]
    )
    candidates = pd.DataFrame(
        [
            {
                "ticker": "000660",
                "name_kr": "SK하이닉스",
                "sector": "전기 전자",
                "source": "ls-industry",
                "updated_at": "2026-06-23",
            }
        ]
    )

    merged = merge_sector_maps(existing, candidates, overwrite=True)

    assert merged.loc[0, "sector"] == "전기 전자"
