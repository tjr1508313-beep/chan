"""data-cache 브랜치에서 SQLite 캐시 DB 를 원격 동기화.

GitHub Actions 가 평일 정기적으로 시세를 갱신해 `data-cache` 브랜치에
`screening_cache.db` 와 `last_updated.txt` 를 orphan force-push 한다.
이 모듈은 앱 시작 시 1회 호출되어:

1. `last_updated.txt` 의 ISO timestamp 를 가볍게 받음 (< 1KB).
2. 로컬에 저장된 "마지막으로 동기화한 remote timestamp" 와 비교.
3. 다르면 `screening_cache.db` 전체를 받아 원자적으로 교체.

설계 메모:
    - 동기화 시점은 **`screening.cache.init_cache()` 호출 전**.
      받은 DB 에 스키마가 부족해도 `init_cache()` 가 보강해줌.
    - 임시 파일(`.db.tmp`)에 받은 뒤 `os.replace()` 로 원자 교체 → 부분 다운로드 시 캐시 손상 방지.
    - 네트워크 실패는 silent. UI 에 작은 배지로만 노출.
    - 사용자가 환경변수 `SCREENING_SKIP_REMOTE_SYNC=1` 로 끄거나
      `SCREENING_CACHE_REPO=owner/repo` 로 다른 레포 가리킬 수 있음.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .cache import DB_PATH

_LOG = logging.getLogger(__name__)

# 기본 원격 (사용자 레포). 환경변수로 오버라이드 가능.
_DEFAULT_REPO = "tjr1508313-beep/chan"
_BRANCH = "data-cache"
_DB_FILENAME = "screening_cache.db"
_STAMP_FILENAME = "last_updated.txt"

# 로컬에 마지막으로 동기화한 원격 timestamp 를 저장. DB 와 같은 폴더.
_LOCAL_STAMP_PATH: Path = DB_PATH.with_name(".remote_cache_stamp.json")

# 네트워크 타임아웃 (초)
_STAMP_TIMEOUT = 5.0
_DB_TIMEOUT = 180.0


SyncStatus = Literal[
    "synced",        # 새 DB 받음
    "up_to_date",    # 로컬 = 원격
    "no_remote",     # 원격에 캐시 없음 (첫 실행 / data-cache 브랜치 미생성)
    "unreachable",   # 네트워크/HTTP 실패
    "disabled",      # 환경변수로 비활성화
    "error",         # 예외
]


@dataclass
class SyncResult:
    status: SyncStatus
    remote_stamp: str | None = None
    remote_kst: str | None = None
    remote_market: str | None = None
    remote_summary: str | None = None
    bytes_downloaded: int = 0
    error: str | None = None
    checked_at: str = ""

    def __post_init__(self) -> None:
        if not self.checked_at:
            self.checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _repo() -> str:
    return os.environ.get("SCREENING_CACHE_REPO", _DEFAULT_REPO).strip() or _DEFAULT_REPO


def _stamp_url() -> str:
    return f"https://raw.githubusercontent.com/{_repo()}/{_BRANCH}/{_STAMP_FILENAME}"


def _db_url() -> str:
    return f"https://raw.githubusercontent.com/{_repo()}/{_BRANCH}/{_DB_FILENAME}"


def _parse_stamp(text: str) -> dict[str, str]:
    """`last_updated.txt` 파싱.

    첫 줄: ISO timestamp (UTC). 이후는 `key=value` 형식의 메타.
    """
    out: dict[str, str] = {}
    if not text:
        return out
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return out
    out["timestamp"] = lines[0].strip()
    for ln in lines[1:]:
        if "=" in ln:
            k, _, v = ln.partition("=")
            out[k.strip()] = v.strip()
    return out


def _load_local_stamp() -> str:
    """로컬에 저장된 마지막 원격 timestamp."""
    if not _LOCAL_STAMP_PATH.exists():
        return ""
    try:
        data = json.loads(_LOCAL_STAMP_PATH.read_text(encoding="utf-8"))
        return str(data.get("remote_stamp") or "")
    except Exception:
        return ""


def _save_local_stamp(result: SyncResult) -> None:
    """동기화 성공 시 원격 timestamp 저장."""
    try:
        _LOCAL_STAMP_PATH.write_text(
            json.dumps(asdict(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        _LOG.warning("Could not write remote_cache_stamp: %s", e)


def get_last_sync_info() -> SyncResult | None:
    """UI 배지용 — 마지막 동기화 결과를 로컬 파일에서 읽음."""
    if not _LOCAL_STAMP_PATH.exists():
        return None
    try:
        data = json.loads(_LOCAL_STAMP_PATH.read_text(encoding="utf-8"))
        return SyncResult(**{k: data.get(k) for k in SyncResult.__dataclass_fields__})
    except Exception:
        return None


def sync_from_remote(force: bool = False) -> SyncResult:
    """원격 캐시 DB 를 로컬로 동기화.

    Args:
        force: True 면 stamp 비교 건너뛰고 무조건 받음.

    Returns:
        SyncResult — UI 가 status 와 timestamp 만 보면 됨.
    """
    if os.environ.get("SCREENING_SKIP_REMOTE_SYNC", "").strip() in ("1", "true", "yes"):
        return SyncResult(status="disabled")

    # requests 가 무거우면 stdlib urllib 으로도 충분
    try:
        import requests  # type: ignore
    except ImportError:
        try:
            return _sync_with_urllib(force)
        except Exception as e:
            return SyncResult(status="error", error=f"urllib fallback: {e}")

    # 1) 원격 stamp 받기
    try:
        r = requests.get(_stamp_url(), timeout=_STAMP_TIMEOUT)
    except Exception as e:
        return SyncResult(status="unreachable", error=str(e))

    if r.status_code == 404:
        return SyncResult(status="no_remote")
    if not r.ok:
        return SyncResult(status="unreachable", error=f"HTTP {r.status_code}")

    meta = _parse_stamp(r.text)
    remote_stamp = meta.get("timestamp", "")
    if not remote_stamp:
        return SyncResult(status="error", error="empty stamp")

    local_stamp = _load_local_stamp()
    if not force and remote_stamp == local_stamp and DB_PATH.exists():
        # 메타만 갱신해서 저장 (KST/market 등 최신화)
        result = SyncResult(
            status="up_to_date",
            remote_stamp=remote_stamp,
            remote_kst=meta.get("kst"),
            remote_market=meta.get("market"),
            remote_summary=meta.get("summary"),
        )
        _save_local_stamp(result)
        return result

    # 2) DB 받기
    try:
        with requests.get(_db_url(), timeout=_DB_TIMEOUT, stream=True) as resp:
            if resp.status_code == 404:
                return SyncResult(status="no_remote", remote_stamp=remote_stamp)
            if not resp.ok:
                return SyncResult(
                    status="unreachable",
                    remote_stamp=remote_stamp,
                    error=f"HTTP {resp.status_code}",
                )
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = DB_PATH.with_suffix(DB_PATH.suffix + ".tmp")
            n = 0
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    if not chunk:
                        continue
                    f.write(chunk)
                    n += len(chunk)
            # SQLite 가 열고 있을 수도 있는 사이드카(WAL/SHM) 정리
            for sidecar in (
                DB_PATH.with_suffix(DB_PATH.suffix + "-wal"),
                DB_PATH.with_suffix(DB_PATH.suffix + "-shm"),
            ):
                try:
                    sidecar.unlink()
                except OSError:
                    pass
            os.replace(tmp, DB_PATH)
    except Exception as e:
        return SyncResult(
            status="error", remote_stamp=remote_stamp, error=str(e)
        )

    result = SyncResult(
        status="synced",
        remote_stamp=remote_stamp,
        remote_kst=meta.get("kst"),
        remote_market=meta.get("market"),
        remote_summary=meta.get("summary"),
        bytes_downloaded=n,
    )
    _save_local_stamp(result)
    return result


def _sync_with_urllib(force: bool) -> SyncResult:
    """`requests` 없을 때의 stdlib 폴백."""
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError

    try:
        req = Request(_stamp_url(), headers={"User-Agent": "screening-app"})
        with urlopen(req, timeout=_STAMP_TIMEOUT) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        if e.code == 404:
            return SyncResult(status="no_remote")
        return SyncResult(status="unreachable", error=f"HTTP {e.code}")
    except URLError as e:
        return SyncResult(status="unreachable", error=str(e))

    meta = _parse_stamp(text)
    remote_stamp = meta.get("timestamp", "")
    if not remote_stamp:
        return SyncResult(status="error", error="empty stamp")

    local_stamp = _load_local_stamp()
    if not force and remote_stamp == local_stamp and DB_PATH.exists():
        result = SyncResult(
            status="up_to_date", remote_stamp=remote_stamp,
            remote_kst=meta.get("kst"), remote_market=meta.get("market"),
            remote_summary=meta.get("summary"),
        )
        _save_local_stamp(result)
        return result

    try:
        req = Request(_db_url(), headers={"User-Agent": "screening-app"})
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = DB_PATH.with_suffix(DB_PATH.suffix + ".tmp")
        n = 0
        with urlopen(req, timeout=_DB_TIMEOUT) as resp, open(tmp, "wb") as f:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                n += len(chunk)
        for sidecar in (
            DB_PATH.with_suffix(DB_PATH.suffix + "-wal"),
            DB_PATH.with_suffix(DB_PATH.suffix + "-shm"),
        ):
            try:
                sidecar.unlink()
            except OSError:
                pass
        os.replace(tmp, DB_PATH)
    except HTTPError as e:
        if e.code == 404:
            return SyncResult(status="no_remote", remote_stamp=remote_stamp)
        return SyncResult(status="unreachable", remote_stamp=remote_stamp, error=f"HTTP {e.code}")
    except URLError as e:
        return SyncResult(status="unreachable", remote_stamp=remote_stamp, error=str(e))
    except Exception as e:
        return SyncResult(status="error", remote_stamp=remote_stamp, error=str(e))

    result = SyncResult(
        status="synced", remote_stamp=remote_stamp,
        remote_kst=meta.get("kst"), remote_market=meta.get("market"),
        remote_summary=meta.get("summary"),
        bytes_downloaded=n,
    )
    _save_local_stamp(result)
    return result
