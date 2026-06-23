"""LS Securities industry/sector helpers for Korean stocks.

The LS OpenAPI "업종" endpoint gives an industry catalog (t8424) and
constituent stocks for one industry (t1516).  This module keeps that HTTP
surface small and returns pandas DataFrames that can be merged into the local
`data/kr_sector_map.csv` workflow.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pandas as pd


_BASE_URL = "https://openapi.ls-sec.co.kr:8080"
_TOKEN_PATH = "/oauth2/token"
_INDUSTRY_PATH = "/indtp/market-data"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DOTENV = _PROJECT_ROOT / ".env"

_BROAD_CODES = {
    "001",  # 종합
    "002",  # 대형주
    "003",  # 중형주
    "004",  # 소형주
    "027",  # KOSPI 제조업
    "301",  # 코스닥 종합
    "306",  # KOSDAQ 제조
}

_KRX_THEME_CODES = {
    "502", "503", "504", "505", "507", "508", "510", "511", "513", "514",
    "516", "517", "527", "528", "531", "532", "533", "534", "535", "548",
    "549", "550", "551", "552",
}


def ls_load_dotenv(path: Path | None = None) -> None:
    """Load local `.env` values into process env without overriding existing env."""
    target = path or _DOTENV
    if not target.exists():
        return
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def ls_configured() -> bool:
    ls_load_dotenv()
    return bool(os.environ.get("LS_APP_KEY") and os.environ.get("LS_APP_SECRET"))


def _post_json(url: str, *, headers: dict[str, str], body: Any, timeout: int) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    try:
        import requests

        response = requests.post(url, headers=headers, data=data, timeout=timeout)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.json()
    except ImportError:
        import urllib.request

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))


def _post_form(url: str, *, headers: dict[str, str], body: str, timeout: int) -> dict:
    try:
        import requests

        response = requests.post(url, headers=headers, data=body, timeout=timeout)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.json()
    except ImportError:
        import urllib.request

        req = urllib.request.Request(
            url, data=body.encode("utf-8"), headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))


def ls_get_access_token(
    app_key: str | None = None,
    app_secret: str | None = None,
    *,
    timeout: int = 15,
) -> str:
    """Issue a client-credentials access token from LS OpenAPI."""
    ls_load_dotenv()
    key = app_key or os.environ.get("LS_APP_KEY", "")
    secret = app_secret or os.environ.get("LS_APP_SECRET", "")
    if not key or not secret:
        raise RuntimeError("LS_APP_KEY/LS_APP_SECRET이 설정되어 있지 않습니다.")

    body = urlencode(
        {
            "grant_type": "client_credentials",
            "appkey": key,
            "appsecretkey": secret,
            "scope": "oob",
        }
    )
    payload = _post_form(
        _BASE_URL + _TOKEN_PATH,
        headers={"content-type": "application/x-www-form-urlencoded"},
        body=body,
        timeout=timeout,
    )
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("LS access_token 발급 응답에 토큰이 없습니다.")
    return str(token)


def _call_industry_tr(
    token: str,
    tr_cd: str,
    body: dict,
    *,
    timeout: int = 15,
) -> dict:
    return _post_json(
        _BASE_URL + _INDUSTRY_PATH,
        headers={
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "tr_cd": tr_cd,
            "tr_cont": "N",
            "tr_cont_key": "",
        },
        body=body,
        timeout=timeout,
    )


def _clean_industry_name(value: object) -> str:
    return "".join(str(value or "").split())


def ls_fetch_industries(
    token: str | None = None,
    *,
    timeout: int = 15,
) -> pd.DataFrame:
    """Fetch LS industry/index code catalog with t8424."""
    access_token = token or ls_get_access_token(timeout=timeout)
    payload = _call_industry_tr(
        access_token,
        "t8424",
        {"t8424InBlock": {"gubun": "0"}},
        timeout=timeout,
    )
    rows = []
    for row in payload.get("t8424OutBlock", []) or []:
        upcode = str(row.get("upcode") or "").strip()
        name = _clean_industry_name(row.get("hname"))
        if upcode and name:
            rows.append({"upcode": upcode.zfill(3), "industry_name": name})
    return pd.DataFrame(rows, columns=["upcode", "industry_name"])


def ls_select_mapping_industries(
    industries: pd.DataFrame,
    *,
    include_krx_theme: bool = False,
    include_broad: bool = False,
) -> pd.DataFrame:
    """Select industry rows useful for stock-to-sector mapping."""
    if industries is None or industries.empty:
        return pd.DataFrame(columns=["upcode", "industry_name"])

    df = industries.copy()
    df["upcode"] = df["upcode"].astype(str).str.zfill(3)
    code_num = pd.to_numeric(df["upcode"], errors="coerce")
    official = code_num.between(5, 30) | code_num.between(303, 338)
    selected = df[official].copy()
    if not include_broad:
        selected = selected[~selected["upcode"].isin(_BROAD_CODES)]

    if include_krx_theme:
        theme = df[df["upcode"].isin(_KRX_THEME_CODES)].copy()
        selected = pd.concat([theme, selected], ignore_index=True)

    return selected.drop_duplicates(subset=["upcode"], keep="first").reset_index(drop=True)


def ls_fetch_industry_members(
    upcode: str,
    token: str | None = None,
    *,
    industry_name: str = "",
    sleep_sec: float = 1.05,
    max_pages: int = 50,
    timeout: int = 15,
) -> pd.DataFrame:
    """Fetch constituent stocks for one LS industry with t1516."""
    access_token = token or ls_get_access_token(timeout=timeout)
    code = str(upcode).strip().zfill(3)
    cursor = ""
    seen_cursors: set[str] = set()
    rows: list[dict] = []

    for page in range(max_pages):
        in_block = {"upcode": code}
        if cursor:
            in_block["shcode"] = cursor
        payload = _call_industry_tr(
            access_token,
            "t1516",
            {"t1516InBlock": in_block},
            timeout=timeout,
        )
        for row in payload.get("t1516OutBlock1", []) or []:
            ticker = str(row.get("shcode") or "").strip().zfill(6)
            name = str(row.get("hname") or "").strip()
            if ticker and ticker.isdigit():
                rows.append(
                    {
                        "ticker": ticker,
                        "name_kr": name,
                        "sector": industry_name,
                        "ls_upcode": code,
                        "source": "ls-industry",
                    }
                )

        next_cursor = str((payload.get("t1516OutBlock") or {}).get("shcode") or "").strip()
        if not next_cursor or next_cursor in seen_cursors or next_cursor == cursor:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
        if sleep_sec > 0 and page < max_pages - 1:
            time.sleep(float(sleep_sec))

    return pd.DataFrame(
        rows,
        columns=["ticker", "name_kr", "sector", "ls_upcode", "source"],
    )


def ls_build_sector_map(
    *,
    include_krx_theme: bool = False,
    include_broad: bool = False,
    max_industries: int | None = None,
    sleep_sec: float = 1.05,
    timeout: int = 15,
) -> pd.DataFrame:
    """Build stock-to-LS-industry mapping candidates."""
    token = ls_get_access_token(timeout=timeout)
    industries = ls_select_mapping_industries(
        ls_fetch_industries(token, timeout=timeout),
        include_krx_theme=include_krx_theme,
        include_broad=include_broad,
    )
    if max_industries is not None:
        industries = industries.head(max(int(max_industries), 0))

    frames = []
    for row in industries.itertuples(index=False):
        frames.append(
            ls_fetch_industry_members(
                row.upcode,
                token,
                industry_name=row.industry_name,
                sleep_sec=sleep_sec,
                timeout=timeout,
            )
        )
        if sleep_sec > 0:
            time.sleep(float(sleep_sec))

    if not frames:
        return pd.DataFrame(
            columns=["ticker", "name_kr", "sector", "source", "updated_at", "ls_upcode"]
        )

    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset=["ticker"], keep="first")
    out["updated_at"] = pd.Timestamp.today().date().isoformat()
    return out[["ticker", "name_kr", "sector", "source", "updated_at", "ls_upcode"]]
