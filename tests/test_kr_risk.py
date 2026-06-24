import pytest

import screening.kr_risk as kr_risk
import screening.ls_sector as ls_sector


def test_skip_when_not_configured(monkeypatch):
    """LS 키 미설정 시 빈 dict 반환 (graceful degrade)."""
    monkeypatch.setattr(ls_sector, "ls_configured", lambda: False)
    assert kr_risk.kr_fetch_risk_flags(sleep_sec=0) == {}


def test_skip_when_token_fails(monkeypatch):
    """토큰 발급 실패 시 빈 dict 반환."""
    monkeypatch.setattr(ls_sector, "ls_configured", lambda: True)

    def boom(*a, **k):
        raise RuntimeError("auth down")

    monkeypatch.setattr(ls_sector, "ls_get_access_token", boom)
    assert kr_risk.kr_fetch_risk_flags(sleep_sec=0) == {}


def _patch_designations(monkeypatch, table):
    monkeypatch.setattr(ls_sector, "ls_configured", lambda: True)
    monkeypatch.setattr(ls_sector, "ls_get_access_token", lambda *a, **k: "tok")

    def fake_fetch(token, tr_cd, jongchk, **kwargs):
        result = table.get((tr_cd, jongchk))
        if isinstance(result, Exception):
            raise result
        return set(result or ())

    monkeypatch.setattr(kr_risk, "_fetch_designation", fake_fetch)


def test_classifies_and_merges_labels(monkeypatch):
    """카테고리별 분류 + 한 종목이 여러 분류에 걸칠 때 label 병합 / is_risk OR."""
    _patch_designations(monkeypatch, {
        ("t1404", "1"): {"000020"},            # 관리종목
        ("t1405", "2"): {"111111"},            # 매매정지
        ("t1405", "3"): {"000020"},            # 정리매매 (관리종목과 중복 → label 2개)
        ("t1404", "4"): {"123456"},            # 투자주의환기 (배지)
        ("t1405", "1"): set(),                 # 투자경고
        ("t1405", "4"): {"123456"},            # 투자주의 (환기와 중복 → 배지 2개)
        ("t1405", "7"): {"222222"},            # 단기과열 (배지)
    })

    result = kr_risk.kr_fetch_risk_flags(sleep_sec=0)

    # 제외 대상
    assert result["000020"]["is_risk"] is True
    assert set(result["000020"]["labels"]) == {"관리종목", "정리매매"}
    assert result["111111"]["is_risk"] is True
    assert result["111111"]["labels"] == ["매매정지"]

    # 배지만 (제외 X)
    assert result["123456"]["is_risk"] is False
    assert set(result["123456"]["labels"]) == {"투자주의환기", "투자주의"}
    assert result["222222"]["is_risk"] is False
    assert result["222222"]["labels"] == ["단기과열"]


def test_one_category_failure_isolated(monkeypatch):
    """한 카테고리 조회가 실패해도 나머지는 정상 수집된다."""
    _patch_designations(monkeypatch, {
        ("t1404", "1"): RuntimeError("관리종목 조회 실패"),  # 이 분류만 실패
        ("t1405", "2"): {"111111"},
    })

    result = kr_risk.kr_fetch_risk_flags(sleep_sec=0)

    assert "000020" not in result          # 실패한 분류는 빠짐
    assert result["111111"]["is_risk"] is True
    assert result["111111"]["labels"] == ["매매정지"]
