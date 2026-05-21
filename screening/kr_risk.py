"""LS증권 REST OpenAPI 기반 한국 관리/거래정지/시장경보 종목 조회.

순수 파이썬 (streamlit/pandas import 금지). os.environ 의 LS_APP_KEY /
LS_APP_SECRET 만 읽는다. 키 미설정 또는 API 실패 시 빈 dict 반환 (graceful degrade).

is_risk = True  ⟸ 관리종목 OR 거래정지/정리매매
labels         = 표시용 전체 지정 텍스트 (관리/거래정지/정리매매/투자경고/투자주의/단기과열)

주의: 정확한 tr_cd / REST 경로 / 응답 블록 필드명은 LS 라이브 테스트베드로 확정해야 한다.
      _collect_raw_designations / _parse_block / _get_token 의 TR 매핑은 구 xingAPI
      (t1404/t1405) 기준 플레이스홀더이며, 실제 응답 스키마에 맞춰 조정한다.
      분류 로직(_classify)은 wire 포맷과 무관하므로 그대로 둔다.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_BASE = "https://openapi.ls-sec.co.kr"
_TOKEN_PATH = "/oauth2/token"
_RISK_DESIGNATIONS = frozenset({"관리", "거래정지", "정리매매"})


def _classify(raw: dict[str, list[str]]) -> dict[str, dict]:
    """지정종류 -> 코드리스트 매핑을 코드별 {is_risk, labels} 로 변환."""
    out: dict[str, dict] = {}
    for designation, codes in raw.items():
        for code in codes:
            c = str(code).strip().zfill(6)
            entry = out.setdefault(c, {"is_risk": False, "labels": []})
            if designation not in entry["labels"]:
                entry["labels"].append(designation)
            if designation in _RISK_DESIGNATIONS:
                entry["is_risk"] = True
    return out


def _http_post(url: str, headers: dict, body: Optional[dict]) -> dict:
    """requests 우선, 없으면 urllib 폴백. JSON dict 반환."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    try:
        import requests  # type: ignore
        resp = requests.post(url, headers=headers, data=data, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except ImportError:
        import urllib.request
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))


def _get_token(app_key: str, app_secret: str) -> str:
    """client_credentials 토큰 발급 (form-urlencoded)."""
    url = _BASE + _TOKEN_PATH
    headers = {"content-type": "application/x-www-form-urlencoded"}
    body = (
        f"grant_type=client_credentials&appkey={app_key}"
        f"&appsecretkey={app_secret}&scope=oob"
    )
    try:
        import requests  # type: ignore
        resp = requests.post(url, headers=headers, data=body, timeout=15)
        resp.raise_for_status()
        return resp.json()["access_token"]
    except ImportError:
        import urllib.request
        req = urllib.request.Request(
            url, data=body.encode("utf-8"), headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))["access_token"]


def _parse_block(payload: dict) -> list[str]:
    """LS TR 응답에서 종목코드 리스트 추출 (실제 스키마 확정 후 조정)."""
    codes: list[str] = []
    for _key, val in payload.items():
        if not isinstance(val, list):
            continue
        for row in val:
            if isinstance(row, dict):
                code = row.get("shcode") or row.get("종목코드") or row.get("code")
                if code:
                    codes.append(str(code).strip().zfill(6))
    return codes


def _collect_raw_designations(token: str) -> dict[str, list[str]]:
    """지정종류별 종목코드 리스트 수집.

    TR 매핑은 구 xingAPI 기준 플레이스홀더 — 라이브 테스트베드로 확정.
    분류는 raw 형태만 맞으면 동작하므로 이 함수만 조정하면 된다.
    """
    raw: dict[str, list[str]] = {}

    def _call(tr_cd: str, path: str, in_block: dict) -> dict:
        url = f"{_BASE}/stock/{path}"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "tr_cd": tr_cd,
            "tr_cont": "N",
        }
        return _http_post(url, headers, in_block)

    mapping = [
        ("관리",     "t1404", "market-data", {"t1404InBlock": {"gubun": "1"}}),
        ("투자주의", "t1404", "market-data", {"t1404InBlock": {"gubun": "3"}}),
        ("거래정지", "t1405", "market-data", {"t1405InBlock": {"gubun": "2"}}),
        ("정리매매", "t1405", "market-data", {"t1405InBlock": {"gubun": "4"}}),
        ("투자경고", "t1405", "market-data", {"t1405InBlock": {"gubun": "5"}}),
        ("단기과열", "t1405", "market-data", {"t1405InBlock": {"gubun": "6"}}),
    ]
    for label, tr_cd, path, in_block in mapping:
        payload = _call(tr_cd, path, in_block)
        raw[label] = _parse_block(payload)
    return raw


def kr_fetch_risk_flags() -> dict[str, dict]:
    """LS OpenAPI 로 지정 종목 조회 후 {code: {is_risk, labels}} 반환.

    키 미설정/API 실패 시 빈 dict + 경고 로그 (graceful degrade).
    """
    app_key = os.environ.get("LS_APP_KEY")
    app_secret = os.environ.get("LS_APP_SECRET")
    if not app_key or not app_secret:
        logger.warning("LS_APP_KEY/LS_APP_SECRET 미설정 — 관리종목 플래그 skip")
        return {}
    try:
        token = _get_token(app_key, app_secret)
        raw = _collect_raw_designations(token)
        return _classify(raw)
    except Exception as exc:  # noqa: BLE001 — 갱신 전체를 막지 않기 위해 광범위 포착
        logger.warning("LS 관리종목 조회 실패 (%s) — 플래그 skip", exc)
        return {}
