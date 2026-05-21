# 한국 관리종목 필터 (LS증권 OpenAPI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 한국 관리종목·거래정지/정리매매를 RS 스크리닝에서 자동 제외하고, 투자경고/투자주의/단기과열은 참고 배지로 표시한다. 데이터 소스는 LS증권 REST OpenAPI.

**Architecture:** 신규 순수파이썬 모듈 `kr_risk.py`가 LS OpenAPI에서 지정 종목 리스트를 받아 `{code: {is_risk, labels}}`로 분류한다. 캐시 `metadata` 테이블에 `caution_flags` 컬럼을 추가하고, 배치가 메타 갱신 **이후** 매번 `update_risk_flags()`로 플래그만 덮어쓴다. 코어/UI는 기존 `exclude_risk` 필터를 그대로 쓰고 `caution_flags`만 표시용으로 흘린다.

**Tech Stack:** Python 3.12, SQLite, `requests`(폴백 `urllib`), pytest, Streamlit.

**Spec:** `docs/superpowers/specs/2026-05-21-kr-risk-filter-ls-design.md`

---

## File Structure

- **Create** `screening/kr_risk.py` — LS OpenAPI 클라이언트 + 지정 분류 (순수 파이썬)
- **Create** `tests/test_kr_risk.py` — 분류/graceful-degrade 테스트
- **Create** `tests/test_cache_risk_flags.py` — 마이그레이션 + update_risk_flags 테스트
- **Create** `tests/test_core_risk.py` — exclude_risk + caution_flags 흐름 테스트
- **Modify** `screening/cache.py` — `caution_flags` 컬럼/마이그레이션/`update_risk_flags`/save·load meta
- **Modify** `screening/core.py` — `_SCREEN_DF_COLUMNS` + build에 `caution_flags`
- **Modify** `screening/batch_kr.py` — `screen_refresh_risk_kr()` 플래그 패스
- **Modify** `scripts/refresh_cache.py` — `_refresh_kr()`에 플래그 패스 호출 (메타 뒤)
- **Modify** `screening/ui.py` — 참고 배지 렌더 + `exclude_risk` 라벨/툴팁
- **Modify** `screening.py` — 로컬 진입점에서 `st.secrets` → `os.environ` 복사
- **Modify** `.github/workflows/refresh-kr.yml` — `LS_APP_KEY`/`LS_APP_SECRET` env 주입
- **Modify** `docs/auto-refresh-setup.md`, `CLAUDE.md`, `.claude/plans/PLAN.md` — 문서

---

## Task 0: 테스트 환경 확인

**Files:** none (환경 점검만)

- [ ] **Step 1: pytest 설치 확인**

Run: `python -m pytest --version`
Expected: 버전 출력. 없으면 `pip install pytest` 후 재실행.

- [ ] **Step 2: tests 디렉터리 생성**

Run: `python -c "import os; os.makedirs('tests', exist_ok=True); open('tests/__init__.py','a').close()"`
Expected: 에러 없음. `tests/__init__.py` 생성됨.

---

## Task 1: 캐시 — caution_flags 컬럼 & update_risk_flags

LS 플래그를 저장할 컬럼과 메타 TTL과 무관한 갱신 함수를 만든다.

**Files:**
- Modify: `screening/cache.py`
- Test: `tests/test_cache_risk_flags.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cache_risk_flags.py`:

```python
import importlib
import sqlite3

import pytest

import screening.cache as cache


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db = tmp_path / "test_cache.db"
    monkeypatch.setattr(cache, "DB_PATH", str(db), raising=False)
    monkeypatch.setattr(cache, "_DB_PATH", str(db), raising=False)
    cache.init_cache()
    return db


def _seed_meta(ticker, **over):
    meta = {
        "name_en": ticker, "name_kr": ticker, "sector": None,
        "country": "South Korea", "exchange": "KOSPI",
        "market_cap": 1e12, "is_china": False, "is_risk": False,
    }
    meta.update(over)
    cache.cache_save_meta(ticker, meta)


def test_migration_adds_caution_flags_column(tmp_db):
    with cache._connect() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(metadata)")}
    assert "caution_flags" in cols


def test_update_risk_flags_sets_and_clears(tmp_db):
    _seed_meta("005930")
    _seed_meta("000660")
    # 005930 관리(is_risk), 000660 투자경고(참고)
    cache.update_risk_flags({
        "005930": {"is_risk": True, "labels": ["관리"]},
        "000660": {"is_risk": False, "labels": ["투자경고"]},
    })
    m1 = cache.cache_load_meta("005930")
    m2 = cache.cache_load_meta("000660")
    assert m1["is_risk"] is True
    assert m1["caution_flags"] == "관리"
    assert m2["is_risk"] is False
    assert m2["caution_flags"] == "투자경고"

    # 다음 갱신에서 005930만 남고 000660은 지정 해제 → 클리어
    cache.update_risk_flags({"005930": {"is_risk": True, "labels": ["관리"]}})
    m2b = cache.cache_load_meta("000660")
    assert m2b["is_risk"] is False
    assert m2b["caution_flags"] is None


def test_update_risk_flags_skips_unknown_ticker(tmp_db):
    # metadata 행 없는 코드는 조용히 skip (행 생성은 메타 갱신 담당)
    cache.update_risk_flags({"999999": {"is_risk": True, "labels": ["관리"]}})
    assert cache.cache_load_meta("999999") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cache_risk_flags.py -v`
Expected: FAIL (`caution_flags` 컬럼 없음 / `update_risk_flags` 미정의).

> 참고: `_connect`/`DB_PATH` 실제 심볼명이 다르면 fixture를 실제 이름에 맞춰 조정한다. `cache.py` 상단에서 DB 경로 상수와 `_connect`를 확인할 것.

- [ ] **Step 3: DDL에 컬럼 추가**

`screening/cache.py` `_DDL_METADATA` 의 `is_risk INTEGER,` 다음 줄에 추가:

```python
    is_risk    INTEGER,
    caution_flags TEXT,
    updated_at TEXT
```

(기존 `updated_at TEXT` 줄은 그대로 두고 그 앞에 `caution_flags TEXT,` 삽입)

- [ ] **Step 4: 마이그레이션 함수 추가 + init_cache에서 호출**

`_migrate_dollar_volume_column` 아래에 추가:

```python
def _migrate_caution_flags_column(conn: sqlite3.Connection) -> None:
    """metadata.caution_flags 컬럼이 없으면 추가 (구 DB / 원격 동기 DB 대응)."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(metadata)").fetchall()}
    if "caution_flags" not in cols:
        conn.execute("ALTER TABLE metadata ADD COLUMN caution_flags TEXT")
```

`init_cache()` 의 `_migrate_dollar_volume_column(conn)` 다음 줄에 추가:

```python
        _migrate_caution_flags_column(conn)
```

- [ ] **Step 5: cache_save_meta / cache_load_meta에 caution_flags 반영**

`cache_save_meta` 의 INSERT 컬럼·VALUES·row 튜플에 `caution_flags` 추가.
`row` 튜플에서 `_bool_to_int(meta.get("is_risk")),` 다음에:

```python
        meta.get("caution_flags"),
```

`sql` 을:

```python
    sql = (
        "INSERT OR REPLACE INTO metadata "
        "(ticker, name_en, name_kr, sector, country, exchange, "
        "market_cap, is_china, is_risk, caution_flags, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
```

`cache_load_meta` SELECT 에 `caution_flags` 추가하고 반환 dict 확장:

```python
        row = conn.execute(
            "SELECT name_en, name_kr, sector, country, exchange, "
            "market_cap, is_china, is_risk, caution_flags, updated_at "
            "FROM metadata WHERE ticker = ?",
            (t,),
        ).fetchone()
    ...
    return {
        "name_en": row[0],
        "name_kr": row[1],
        "sector": row[2],
        "country": row[3],
        "exchange": row[4],
        "market_cap": row[5],
        "is_china": bool(row[6]) if row[6] is not None else None,
        "is_risk": bool(row[7]) if row[7] is not None else None,
        "caution_flags": row[8],
        "updated_at": row[9],
    }
```

> 주의: `cache_save_meta`는 `INSERT OR REPLACE`로 행 전체를 덮어쓴다. `kr_get_meta`는 `caution_flags`를 만들지 않으므로 메타 갱신 시 이 컬럼이 NULL로 덮인다. 그래서 배치는 **메타 갱신 후** 플래그 패스를 돌려 복원한다(Task 3). 메타가 TTL로 skip되면 cache_save_meta가 호출되지 않아 기존 값이 보존된다.

- [ ] **Step 6: update_risk_flags 추가**

`cache_load_meta` 아래에 추가:

```python
def update_risk_flags(flags: dict) -> None:
    """메타 TTL과 무관하게 is_risk / caution_flags 두 컬럼만 갱신.

    flags: { code: {"is_risk": bool, "labels": list[str]} }
    - metadata 행이 이미 있는 코드만 UPDATE (행 생성은 메타 갱신 담당).
    - flags 에 없는 모든 종목은 두 컬럼을 클리어(NULL/0)해 지정 해제를 반영.
    """
    with _connect() as conn:
        existing = {r[0] for r in conn.execute("SELECT ticker FROM metadata").fetchall()}
        # 1) 전체 클리어 (지정 해제 반영)
        conn.execute("UPDATE metadata SET is_risk = 0, caution_flags = NULL")
        # 2) flags 적용 (행 있는 코드만)
        for code, info in flags.items():
            t = str(code).strip().upper()
            if t not in existing:
                continue
            labels = info.get("labels") or []
            caution = ",".join(labels) if labels else None
            conn.execute(
                "UPDATE metadata SET is_risk = ?, caution_flags = ? WHERE ticker = ?",
                (1 if info.get("is_risk") else 0, caution, t),
            )
```

> 설계 메모: 전체 클리어는 미국 종목의 `is_risk`도 0으로 만든다. 미국 `is_risk`는 현재 항상 False(`data.py:257`)이므로 무해하다. 만약 추후 미국 `is_risk`가 의미를 가지면 클리어를 한국 코드(6자리 숫자)로 한정해야 한다 — 지금은 YAGNI.

- [ ] **Step 7: Run test to verify it passes**

Run: `python -m pytest tests/test_cache_risk_flags.py -v`
Expected: PASS (3 tests).

- [ ] **Step 8: Commit**

```bash
git add screening/cache.py tests/test_cache_risk_flags.py tests/__init__.py
git commit -m "feat(cache): caution_flags 컬럼 + update_risk_flags 추가"
```

---

## Task 2: kr_risk.py — LS OpenAPI 클라이언트 & 분류

LS에서 지정 종목을 받아 `{code: {is_risk, labels}}`로 분류. HTTP 계층과 분류 계층을 분리해 분류만 단위 테스트한다.

**Files:**
- Create: `screening/kr_risk.py`
- Test: `tests/test_kr_risk.py`

- [ ] **Step 1: Write the failing test**

`tests/test_kr_risk.py`:

```python
import screening.kr_risk as kr_risk


def test_classify_merges_designations():
    # raw: 지정종류 -> 코드 리스트 (LS TR 파싱 후 표준화된 중간형태)
    raw = {
        "관리": ["005930"],
        "거래정지": ["111111"],
        "정리매매": ["222222"],
        "투자경고": ["005930", "333333"],
        "투자주의": ["444444"],
        "단기과열": ["005930"],
    }
    out = kr_risk._classify(raw)

    # 005930: 관리(is_risk) + 투자경고 + 단기과열 라벨 모두 보존
    assert out["005930"]["is_risk"] is True
    assert set(out["005930"]["labels"]) == {"관리", "투자경고", "단기과열"}

    # 거래정지/정리매매 → is_risk
    assert out["111111"]["is_risk"] is True
    assert out["222222"]["is_risk"] is True

    # 참고만 (제외 안 함)
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
    # 예외를 삼키고 빈 dict 반환 (graceful degrade)
    assert kr_risk.kr_fetch_risk_flags() == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_kr_risk.py -v`
Expected: FAIL (모듈 없음).

- [ ] **Step 3: kr_risk.py 작성**

`screening/kr_risk.py`:

```python
"""LS증권 REST OpenAPI 기반 한국 관리/거래정지/시장경보 종목 조회.

순수 파이썬 (streamlit import 금지). os.environ 의 LS_APP_KEY / LS_APP_SECRET
만 읽는다. 키 미설정 또는 API 실패 시 빈 dict 반환 (graceful degrade).

is_risk = True  ⟸ 관리종목 OR 거래정지/정리매매
labels         = 표시용 전체 지정 텍스트 (관리/거래정지/정리매매/투자경고/투자주의/단기과열)

주의: 정확한 tr_cd / 응답 블록 필드명은 LS 라이브 테스트베드로 확정해야 한다.
      아래 _collect_raw_designations 의 TR 매핑은 구 xingAPI(t1404/t1405) 기준
      플레이스홀더이며, 실제 응답 스키마에 맞춰 _parse_block 을 조정한다.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_BASE = "https://openapi.ls-sec.co.kr"
_TOKEN_PATH = "/oauth2/token"

# is_risk=True 로 분류할 지정 (제외 대상)
_RISK_DESIGNATIONS = frozenset({"관리", "거래정지", "정리매매"})


# ---------------------------------------------------------------------------
# 분류 (HTTP 무관 — 단위 테스트 대상)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# HTTP 계층
# ---------------------------------------------------------------------------

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
    """client_credentials 토큰 발급."""
    url = _BASE + _TOKEN_PATH
    headers = {"content-type": "application/x-www-form-urlencoded"}
    body = (
        f"grant_type=client_credentials&appkey={app_key}"
        f"&appsecretkey={app_secret}&scope=oob"
    )
    # 토큰 엔드포인트는 form-urlencoded — _http_post 대신 직접 처리
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
    """LS TR 응답에서 종목코드 리스트 추출.

    실제 응답 스키마 확정 후 OutBlock 키/필드명에 맞춰 조정.
    구 xingAPI 는 보통 't1404OutBlock1' 같은 배열 블록 + 'shcode' 필드.
    """
    codes: list[str] = []
    for key, val in payload.items():
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

    TR 매핑 (구 xingAPI 기준 플레이스홀더 — 라이브에서 확정):
      t1404 → 관리 / 투자주의(불성실/투자유의 gubun 분기)
      t1405 → 거래정지 / 정리매매 / 시장경보(투자경고/투자위험)
    실제 LS REST 경로/헤더/InBlock 은 테스트베드 확인 후 채운다.
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

    # NOTE: 아래 4개 호출의 tr_cd/path/in_block/응답분기는 라이브 확정 대상.
    # 분류 로직(_classify)은 raw 형태만 맞으면 동작하므로 여기만 조정하면 된다.
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


# ---------------------------------------------------------------------------
# public
# ---------------------------------------------------------------------------

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_kr_risk.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add screening/kr_risk.py tests/test_kr_risk.py
git commit -m "feat(kr_risk): LS OpenAPI 관리종목 조회 + 지정 분류"
```

---

## Task 3: 배치 — 플래그 패스 (메타 갱신 뒤)

메타 갱신 후 매 실행 시 `update_risk_flags` 를 돌린다.

**Files:**
- Modify: `screening/batch_kr.py`
- Modify: `scripts/refresh_cache.py`

- [ ] **Step 1: batch_kr에 플래그 패스 함수 추가**

`screening/batch_kr.py` 상단 import 에 추가:

```python
from . import kr_risk
```

`screen_refresh_meta_kr` 아래에 추가:

```python
def screen_refresh_risk_kr() -> dict:
    """LS OpenAPI 로 관리/거래정지/시장경보 플래그를 갱신 (메타 TTL 무관, 매 실행).

    메타 갱신 *이후* 호출해야 한다 (cache_save_meta 가 caution_flags 를 NULL 로
    덮으므로). LS 키 미설정/실패 시 flags 빈 dict → 전체 클리어가 되지 않도록
    빈 경우엔 갱신을 건너뛴다.
    """
    cache.init_cache()
    flags = kr_risk.kr_fetch_risk_flags()
    if not flags:
        return {"updated": 0, "skipped": True}
    cache.update_risk_flags(flags)
    return {"updated": len(flags), "skipped": False}
```

> 주의: `flags` 가 비면(키 없음/실패) `update_risk_flags` 를 호출하지 않는다. 그렇지 않으면 전체 클리어로 기존 플래그가 날아간다.

- [ ] **Step 2: Write the failing test**

`tests/test_core_risk.py` 에 배치 동작 테스트 추가 (이 파일은 Task 4에서도 쓴다):

```python
import screening.batch_kr as batch_kr
import screening.cache as cache


def test_refresh_risk_skips_when_no_flags(tmp_path, monkeypatch):
    db = tmp_path / "c.db"
    monkeypatch.setattr(cache, "DB_PATH", str(db), raising=False)
    monkeypatch.setattr(cache, "_DB_PATH", str(db), raising=False)
    cache.init_cache()
    cache.cache_save_meta("005930", {
        "name_en": "x", "name_kr": "x", "sector": None, "country": "South Korea",
        "exchange": "KOSPI", "market_cap": 1e12, "is_china": False, "is_risk": True,
        "caution_flags": "관리",
    })
    monkeypatch.setattr(batch_kr.kr_risk, "kr_fetch_risk_flags", lambda: {})
    res = batch_kr.screen_refresh_risk_kr()
    assert res["skipped"] is True
    # 빈 flags 일 때 기존 값 보존 (전체 클리어 안 함)
    assert cache.cache_load_meta("005930")["is_risk"] is True
```

- [ ] **Step 3: Run test to verify it fails then passes**

Run: `python -m pytest tests/test_core_risk.py::test_refresh_risk_skips_when_no_flags -v`
Expected: 처음엔 import/속성 에러 가능 → Step 1 적용 후 PASS.

- [ ] **Step 4: refresh_cache.py에서 메타 뒤에 호출**

`scripts/refresh_cache.py` `_refresh_kr()` 의 메타 블록 다음(`return out` 앞)에 추가:

```python
    # 관리/거래정지/시장경보 플래그 — 메타 갱신 *후* (caution_flags 복원), 매 실행
    out["risk"] = batch_kr.screen_refresh_risk_kr()
```

- [ ] **Step 5: Run full suite**

Run: `python -m pytest tests/ -v`
Expected: 전부 PASS.

- [ ] **Step 6: Commit**

```bash
git add screening/batch_kr.py scripts/refresh_cache.py tests/test_core_risk.py
git commit -m "feat(batch): 메타 갱신 후 LS 관리종목 플래그 패스"
```

---

## Task 4: 코어 — caution_flags를 스크리닝 DF에 전달

`exclude_risk` 필터는 변경 없음. `caution_flags` 만 표시용으로 흘린다.

**Files:**
- Modify: `screening/core.py`
- Test: `tests/test_core_risk.py`

- [ ] **Step 1: Write the failing test**

`tests/test_core_risk.py` 에 추가:

```python
import pandas as pd
import screening.core as core


def test_screening_df_includes_caution_flags():
    assert "caution_flags" in core._SCREEN_DF_COLUMNS


def test_exclude_risk_filters_is_risk_rows():
    df = pd.DataFrame(
        {
            "last_price": [100.0, 100.0],
            "avg_traded_value_20d": [1e11, 1e11],
            "max_daily_range_20d": [0.1, 0.1],
            "recent_atr_drop_mult": [0.0, 0.0],
            "market_cap": [1e12, 1e12],
            "is_china": [False, False],
            "is_risk": [False, True],
            "caution_flags": ["투자경고", "관리"],
            "name_en": ["A", "B"],
            "name_kr": ["A", "B"],
            "sector": [None, None],
            "country": ["South Korea", "South Korea"],
        },
        index=pd.Index(["000001", "000002"], name="ticker"),
    )
    cfg = core._default_config()
    cfg.update({"min_price": 0, "min_traded_value": 0, "min_market_cap": 0,
                "max_atr_drop_multiple": 0, "exclude_china": False, "exclude_risk": True})
    out = core.screen_apply_filters(df, cfg)
    assert "000002" not in out.index   # is_risk 제외
    assert "000001" in out.index       # 투자경고는 통과 (참고만)
    assert out.loc["000001", "caution_flags"] == "투자경고"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_core_risk.py -v`
Expected: `test_screening_df_includes_caution_flags` FAIL.

> `screen_apply_filters` 시그니처/필수 컬럼이 다르면 실제 구현에 맞춰 cfg 키와 더미 컬럼을 조정한다. `core._default_config()` 와 `_SCREEN_DF_COLUMNS` 를 먼저 확인할 것.

- [ ] **Step 3: _SCREEN_DF_COLUMNS에 추가**

`screening/core.py` `_SCREEN_DF_COLUMNS` 의 `"is_risk",` 다음에 `"caution_flags",` 추가.

- [ ] **Step 4: build에서 채우기**

`screen_build_screening_df` 의 row dict 에서 `"is_risk": is_risk,` 다음에 추가:

```python
                "caution_flags": meta.get("caution_flags"),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_core_risk.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add screening/core.py tests/test_core_risk.py
git commit -m "feat(core): caution_flags 스크리닝 DF 전달 (표시 전용)"
```

---

## Task 5: UI — 참고 배지 & 체크박스 라벨

**Files:**
- Modify: `screening/ui.py`

- [ ] **Step 1: 랭킹 테이블에 참고 배지 추가**

`screening/ui.py` 의 랭킹 행 렌더에서 종목명 표시 부분을 찾는다 (기존 "5일선 이탈 배지" 렌더 패턴 참고 — `grep -n "배지\|badge\|5일선" screening/ui.py`). 종목명 옆에 `caution_flags` 가 있으면 짧은 태그를 붙인다:

```python
caution = row.get("caution_flags")
if caution:
    short = "·".join(
        {"투자경고": "투경", "투자주의": "투주", "단기과열": "과열",
         "관리": "관리", "거래정지": "정지", "정리매매": "정리"}.get(x, x)
        for x in str(caution).split(",")
    )
    name_html += f' <span class="scr-caution-badge">{short}</span>'
```

(실제 종목명 셀 구성 방식 — `st.markdown` HTML vs DataFrame 컬럼 — 에 맞춰 적용. DataFrame 방식이면 `caution_flags` 를 표시 컬럼으로 추가하고 짧은 라벨로 매핑.)

- [ ] **Step 2: 배지 CSS 추가**

`screening/theme.py` 에 (기존 배지 CSS 옆) 추가:

```python
    .scr-caution-badge {
        display: inline-block; font-size: 0.7rem; font-weight: 600;
        color: #b45309; background: #fef3c7; border-radius: 4px;
        padding: 1px 5px; margin-left: 4px; vertical-align: middle;
    }
```

- [ ] **Step 3: exclude_risk 체크박스 라벨/툴팁 갱신**

`screening/ui.py:440` 근처 `exclude_risk` 체크박스의 label/help 를 수정:

```python
            exclude_risk = st.checkbox(
                "관리·거래정지/정리매매 제외",
                key=_key(spec, "filter_exclude_risk"),
                help=(
                    "LS증권 데이터 기반 관리종목·거래정지·정리매매 종목을 제외합니다. "
                    "투자경고/투자주의/단기과열은 제외하지 않고 참고 배지로만 표시합니다."
                ),
                value=True,
            )
```

(미국 섹션에도 같은 체크박스가 공유되면 라벨이 어색하지 않은지 확인 — 공통 함수면 한국 데이터에만 배지가 뜨므로 무해.)

- [ ] **Step 4: 앱 실행 후 시각 검증**

Run: `python -m streamlit run screening.py` (또는 preview_start)
확인: 한국 랭킹 테이블에서 관리/투경 지정 종목이 있으면 배지가 보이고, `exclude_risk` 체크 시 관리/정지/정리 종목이 사라지는지. (LS 키 없으면 배지는 안 뜨지만 크래시 없이 동작해야 함.)

- [ ] **Step 5: Commit**

```bash
git add screening/ui.py screening/theme.py
git commit -m "feat(ui): 관리종목 참고 배지 + exclude_risk 라벨 갱신"
```

---

## Task 6: 시크릿 로딩 & 워크플로우 & 문서

**Files:**
- Modify: `screening.py`
- Modify: `.github/workflows/refresh-kr.yml`
- Modify: `docs/auto-refresh-setup.md`, `CLAUDE.md`, `.claude/plans/PLAN.md`

- [ ] **Step 1: 진입점에서 st.secrets → os.environ 복사**

`screening.py` `main()` 안, `st.set_page_config` 이후 / 페이지 렌더 전에 추가:

```python
    import os
    for _src, _dst in (("ls_app_key", "LS_APP_KEY"), ("ls_app_secret", "LS_APP_SECRET")):
        try:
            if _dst not in os.environ and _src in st.secrets:
                os.environ[_dst] = str(st.secrets[_src])
        except Exception:
            pass  # secrets.toml 없으면 무시 (graceful)
```

- [ ] **Step 2: refresh-kr.yml에 env 주입**

`.github/workflows/refresh-kr.yml` 의 `Run refresh` 스텝에 `env:` 추가:

```yaml
      - name: Run refresh
        id: refresh
        env:
          LS_APP_KEY: ${{ secrets.LS_APP_KEY }}
          LS_APP_SECRET: ${{ secrets.LS_APP_SECRET }}
        run: |
          mkdir -p .ci-out
          python -m scripts.refresh_cache --market kr --json-out .ci-out/result.json
        continue-on-error: true
```

- [ ] **Step 3: 문서 갱신**

`docs/auto-refresh-setup.md` 에 LS 키 세팅 절 추가 (조회전용 키 발급, 로컬 secrets.toml, GH Secrets `LS_APP_KEY`/`LS_APP_SECRET`).

`CLAUDE.md` 공통 필터 4번 "위험종목·관리종목 제외" 의 한국 항목을 "보류" → "LS증권 OpenAPI 적용 (관리/거래정지/정리매매 제외, 투경/투주/과열 참고 배지)" 로 수정. 보류 항목 절도 갱신.

`.claude/plans/PLAN.md` Phase 2 보류 항목 → 완료로 이전, 새 섹션 "한국 관리종목 필터 (LS) ✅" 추가.

- [ ] **Step 4: 전체 테스트 + 커밋**

Run: `python -m pytest tests/ -v`
Expected: 전부 PASS.

```bash
git add screening.py .github/workflows/refresh-kr.yml docs/auto-refresh-setup.md CLAUDE.md .claude/plans/PLAN.md
git commit -m "feat: LS 키 로딩 + 워크플로우 env + 문서 갱신"
```

---

## 구현 후 사용자 세팅 (잔여)

1. LS증권 계좌 + OpenAPI 앱 등록 → **조회전용** App Key/Secret 발급
2. 로컬 `.streamlit/secrets.toml` 에 `ls_app_key`/`ls_app_secret` 입력
3. GitHub 레포 Settings → Secrets 에 `LS_APP_KEY`, `LS_APP_SECRET` 등록
4. `kr_risk._collect_raw_designations` 의 tr_cd/path/InBlock/`_parse_block` 을 LS 라이브 테스트베드 응답에 맞춰 확정

## 미해결 / 구현 중 확인

- **LS tr_cd 확정**: t1404/t1405 매핑은 플레이스홀더. 라이브에서 실제 REST 경로·헤더·응답 블록 확인 후 `_collect_raw_designations`/`_parse_block` 조정 (분류 로직은 불변).
- **단기과열 별도 TR**: 단기과열이 t1405 gubun 으로 안 나오면 별도 TR 추가 (`mapping` 리스트에 한 줄).
