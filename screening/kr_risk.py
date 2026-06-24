"""한국주식 관리종목·거래정지·정리매매 등 지정 종목 조회 (LS증권 OpenAPI).

LS증권 국내주식 시세 TR로 지정 종목 리스트를 받아 분류한다.
인증·HTTP는 `screening.ls_sector`의 OAuth 토큰/POST 헬퍼를 재사용한다 (streamlit 비의존).

  t1404 (관리/불성실/투자유의조회):
      jongchk 1=관리종목 · 2=불성실공시 · 3=투자유의 · 4=투자환기
  t1405 (투자경고/매매정지/정리매매조회):
      jongchk 1=투자경고 · 2=매매정지 · 3=정리매매 · 4=투자주의 ·
              5=투자위험 · 6=위험예고 · 7=단기과열 · 8=이상급등 · 9=상장주식수부족

is_risk = True  ⟸ 관리종목 / 매매정지(거래정지) / 정리매매  → 스크리닝에서 제외
labels         ⟸ 위 + 투자주의환기/투자경고/투자주의/단기과열 (표시용 배지)

설계 메모:
    LS_APP_KEY/LS_APP_SECRET 미설정 또는 조회 실패 시 빈 dict 반환 (graceful degrade).
    과거 2026-06-15에 "t1404/t1405가 전체 종목을 반환한다"고 본 것은 `jongchk`
    파라미터 누락(시장구분 gubun과 혼동)으로 인한 호출 버그였고, gubun/jongchk를
    정확히 주면 카테고리별 지정 종목만 반환됨이 2026-06-24 라이브로 재확인됨.
"""

from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)

_MARKET_DATA_PATH = "/stock/market-data"

# (label, tr_cd, jongchk, is_risk)
_DESIGNATIONS: tuple[tuple[str, str, str, bool], ...] = (
    ("관리종목", "t1404", "1", True),
    ("매매정지", "t1405", "2", True),
    ("정리매매", "t1405", "3", True),
    ("투자주의환기", "t1404", "4", False),
    ("투자경고", "t1405", "1", False),
    ("투자주의", "t1405", "4", False),
    ("단기과열", "t1405", "7", False),
)


def _post_market_data(
    token: str,
    tr_cd: str,
    body: dict,
    *,
    tr_cont: str = "N",
    tr_cont_key: str = "",
    timeout: int = 15,
) -> tuple[dict, dict]:
    """POST /stock/market-data 후 (JSON 본문, 소문자화한 응답 헤더) 반환."""
    from .ls_sector import _BASE_URL  # base url 재사용

    url = _BASE_URL + _MARKET_DATA_PATH
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "tr_cd": tr_cd,
        "tr_cont": tr_cont,
        "tr_cont_key": tr_cont_key,
    }
    data = json.dumps(body).encode("utf-8")
    try:
        import requests

        resp = requests.post(url, headers=headers, data=data, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return resp.json(), {k.lower(): v for k, v in resp.headers.items()}
    except ImportError:
        import urllib.request

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            return payload, hdrs


def _fetch_designation(
    token: str,
    tr_cd: str,
    jongchk: str,
    *,
    sleep_sec: float = 1.05,
    max_pages: int = 30,
    timeout: int = 15,
) -> set[str]:
    """한 카테고리(tr_cd+jongchk)의 지정 종목 코드 집합 수집.

    LS 연속조회: 응답 헤더 ``tr_cont == "Y"`` 이면 다음 페이지가 있으며,
    다음 요청에 헤더 ``tr_cont="Y"`` + ``tr_cont_key``(이전 응답 헤더값)와
    InBlock ``cts_shcode``(이전 페이지 마지막 종목코드)를 넣어 이어받는다.
    (InBlock cts_shcode만으로는 같은 페이지가 반복되므로 헤더 연속조회 필수)
    """
    in_name = f"{tr_cd}InBlock"
    out_rows_key = f"{tr_cd}OutBlock1"

    codes: set[str] = set()
    cts_shcode = " "
    tr_cont = "N"
    tr_cont_key = ""

    for page in range(max_pages):
        body = {in_name: {"gubun": "0", "jongchk": jongchk, "cts_shcode": cts_shcode}}
        payload, hdrs = _post_market_data(
            token, tr_cd, body, tr_cont=tr_cont, tr_cont_key=tr_cont_key, timeout=timeout
        )

        last_shcode = ""
        for row in payload.get(out_rows_key, []) or []:
            raw = str(row.get("shcode") or "").strip()
            if not raw:
                continue
            last_shcode = raw
            code = raw.zfill(6)
            if code.isdigit():
                codes.add(code)

        if hdrs.get("tr_cont") != "Y" or not last_shcode:
            break
        cts_shcode = last_shcode
        tr_cont = "Y"
        tr_cont_key = hdrs.get("tr_cont_key", "")
        if sleep_sec > 0 and page < max_pages - 1:
            time.sleep(float(sleep_sec))

    return codes


def kr_fetch_risk_flags(*, sleep_sec: float = 1.05) -> dict[str, dict]:
    """LS 지정 종목 조회 → {code6: {"is_risk": bool, "labels": list[str]}}.

    LS 키 미설정 또는 조회 실패 시 빈 dict + 경고 로그 (graceful degrade).
    카테고리 하나가 실패해도 나머지는 계속 수집한다.
    """
    try:
        from .ls_sector import ls_configured, ls_get_access_token
    except Exception as exc:  # pragma: no cover - import guard
        logger.warning("ls_sector 임포트 실패 (%s) — 위험종목 플래그 skip", exc)
        return {}

    if not ls_configured():
        logger.warning("LS_APP_KEY/LS_APP_SECRET 미설정 — 위험종목 플래그 skip")
        return {}

    try:
        token = ls_get_access_token()
    except Exception as exc:
        logger.warning("LS access_token 발급 실패 (%s) — 위험종목 플래그 skip", exc)
        return {}

    out: dict[str, dict] = {}
    for idx, (label, tr_cd, jongchk, is_risk) in enumerate(_DESIGNATIONS):
        try:
            codes = _fetch_designation(token, tr_cd, jongchk, sleep_sec=sleep_sec)
        except Exception as exc:
            logger.warning("LS %s(%s jongchk=%s) 조회 실패 (%s) — 해당 분류 skip",
                           label, tr_cd, jongchk, exc)
            continue

        for code in codes:
            entry = out.setdefault(code, {"is_risk": False, "labels": []})
            if is_risk:
                entry["is_risk"] = True
            if label not in entry["labels"]:
                entry["labels"].append(label)

        if sleep_sec > 0 and idx < len(_DESIGNATIONS) - 1:
            time.sleep(float(sleep_sec))

    logger.info("LS 위험종목 조회 완료: 총 %d개 (is_risk=%d, 배지=%d)",
                len(out),
                sum(1 for v in out.values() if v["is_risk"]),
                sum(1 for v in out.values() if not v["is_risk"]))
    return out
