import pandas as pd

import screening.ls_sector as ls_sector


def test_select_mapping_industries_excludes_broad_and_can_include_krx_theme():
    industries = pd.DataFrame(
        [
            {"upcode": "001", "industry_name": "종합"},
            {"upcode": "013", "industry_name": "전기 전자"},
            {"upcode": "027", "industry_name": "제조업"},
            {"upcode": "306", "industry_name": "제조"},
            {"upcode": "324", "industry_name": "전기/전자"},
            {"upcode": "503", "industry_name": "KRX반도체"},
        ]
    )

    selected = ls_sector.ls_select_mapping_industries(
        industries, include_krx_theme=True
    )

    assert list(selected["upcode"]) == ["503", "013", "324"]


def test_fetch_industry_members_follows_shcode_cursor(monkeypatch):
    payloads = [
        {
            "t1516OutBlock": {"shcode": "000002"},
            "t1516OutBlock1": [
                {"shcode": "000001", "hname": "Alpha"},
                {"shcode": "000002", "hname": "Beta"},
            ],
        },
        {
            "t1516OutBlock": {"shcode": ""},
            "t1516OutBlock1": [{"shcode": "000003", "hname": "Gamma"}],
        },
    ]
    calls = []

    def fake_call(token, tr_cd, body, *, timeout=15):
        calls.append((tr_cd, body))
        return payloads.pop(0)

    monkeypatch.setattr(ls_sector, "_call_industry_tr", fake_call)

    members = ls_sector.ls_fetch_industry_members(
        "013",
        token="token",
        industry_name="전기 전자",
        sleep_sec=0,
    )

    assert "shcode" not in calls[0][1]["t1516InBlock"]
    assert calls[1][1]["t1516InBlock"]["shcode"] == "000002"
    assert list(members["ticker"]) == ["000001", "000002", "000003"]
    assert set(members["sector"]) == {"전기 전자"}


def test_fetch_industries_parses_t8424(monkeypatch):
    monkeypatch.setattr(
        ls_sector,
        "_call_industry_tr",
        lambda *args, **kwargs: {
            "t8424OutBlock": [
                {"upcode": "13", "hname": "전 기 전 자"},
                {"upcode": "324", "hname": "전 기/전 자"},
            ]
        },
    )

    industries = ls_sector.ls_fetch_industries(token="token")

    assert industries.to_dict("records") == [
        {"upcode": "013", "industry_name": "전기전자"},
        {"upcode": "324", "industry_name": "전기/전자"},
    ]
