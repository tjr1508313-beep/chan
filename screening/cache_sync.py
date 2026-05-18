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
    "auth_required", # private 레포인데 토큰 미설정 / 권한 부족
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
    """Legacy 비압축 DB URL (구버전 워크플로우 호환용 폴백)."""
    return f"https://raw.githubusercontent.com/{_repo()}/{_BRANCH}/{_DB_FILENAME}"


def _db_gz_url() -> str:
    """gzip 압축 DB URL — GitHub 100MB 파일 제한 회피용 (정상 경로)."""
    return f"https://raw.githubusercontent.com/{_repo()}/{_BRANCH}/{_DB_FILENAME}.gz"


def _decompress_gz(src: Path, dst: Path) -> None:
    """gzip 해제: src.gz → dst. src 는 작업 후 삭제."""
    import gzip
    with gzip.open(src, "rb") as fsrc, open(dst, "wb") as fdst:
        while True:
            chunk = fsrc.read(1 << 20)
            if not chunk:
                break
            fdst.write(chunk)
    try:
        src.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# DB 다운로드 헬퍼 — .db.gz 우선, legacy .db 폴백
# ---------------------------------------------------------------------------
#
# 반환: (bytes_downloaded, status)
#   status==None       → 성공, tmp 에 압축 해제된 DB 준비됨
#   status=="no_remote"     → 양쪽 URL 모두 404
#   status=="auth_required" → 401/403 (private 레포 토큰 부족)
#   status=="<에러문자열>"  → 기타 HTTP/네트워크 실패

def _fetch_db_via_requests(tmp: Path, headers: dict, requests_mod) -> tuple[int, str | None]:
    tmp_gz = tmp.with_suffix(tmp.suffix + ".gz")

    # 1) .db.gz 시도 (정상 경로)
    try:
        with requests_mod.get(_db_gz_url(), timeout=_DB_TIMEOUT, stream=True, headers=headers) as resp:
            if resp.status_code in (401, 403):
                return (0, "auth_required")
            if resp.ok:
                n = 0
                with open(tmp_gz, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1 << 20):
                        if not chunk:
                            continue
                        f.write(chunk)
                        n += len(chunk)
                try:
                    _decompress_gz(tmp_gz, tmp)
                except Exception as e:
                    try:
                        tmp_gz.unlink()
                    except OSError:
                        pass
                    return (0, f"decompress: {e}")
                return (n, None)
            if resp.status_code != 404:
                return (0, f"HTTP {resp.status_code}")
    except Exception as e:
        return (0, str(e))

    # 2) legacy .db 폴백 — 구버전 워크플로우와의 호환
    with requests_mod.get(_db_url(), timeout=_DB_TIMEOUT, stream=True, headers=headers) as resp:
        if resp.status_code == 404:
            return (0, "no_remote")
        if resp.status_code in (401, 403):
            return (0, "auth_required")
        if not resp.ok:
            return (0, f"HTTP {resp.status_code}")
        n = 0
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                if not chunk:
                    continue
                f.write(chunk)
                n += len(chunk)
        return (n, None)


def _fetch_db_via_urllib(tmp: Path, headers: dict) -> tuple[int, str | None]:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError

    tmp_gz = tmp.with_suffix(tmp.suffix + ".gz")

    # 1) .db.gz 시도
    try:
        req = Request(_db_gz_url(), headers=headers)
        n = 0
        with urlopen(req, timeout=_DB_TIMEOUT) as resp, open(tmp_gz, "wb") as f:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                n += len(chunk)
        try:
            _decompress_gz(tmp_gz, tmp)
        except Exception as e:
            try:
                tmp_gz.unlink()
            except OSError:
                pass
            return (0, f"decompress: {e}")
        return (n, None)
    except HTTPError as e:
        if e.code in (401, 403):
            return (0, "auth_required")
        if e.code != 404:
            return (0, f"HTTP {e.code}")
        # 404 → legacy 폴백으로 진행
    except URLError as e:
        return (0, str(e))

    # 2) legacy .db 폴백
    try:
        req = Request(_db_url(), headers=headers)
        n = 0
        with urlopen(req, timeout=_DB_TIMEOUT) as resp, open(tmp, "wb") as f:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                n += len(chunk)
        return (n, None)
    except HTTPError as e:
        if e.code == 404:
            return (0, "no_remote")
        if e.code in (401, 403):
            return (0, "auth_required")
        return (0, f"HTTP {e.code}")
    except URLError as e:
        return (0, str(e))


def _get_auth_token() -> str:
    """PAT 토큰을 환경변수 또는 streamlit secrets 에서 읽음.

    우선순위:
        1. 환경변수 `SCREENING_CACHE_TOKEN`
        2. `.streamlit/secrets.toml` 의 `github_cache_token`

    private 레포일 때만 필요. public 레포면 빈 문자열 반환해도 raw URL 작동.
    """
    tok = os.environ.get("SCREENING_CACHE_TOKEN", "").strip()
    if tok:
        return tok
    try:
        import streamlit as st  # 옵셔널 — CLI 에서는 미import
        try:
            tok = str(st.secrets.get("github_cache_token", "") or "")
        except (FileNotFoundError, AttributeError, KeyError):
            tok = ""
    except ImportError:
        tok = ""
    return tok.strip()


def _auth_headers() -> dict[str, str]:
    """raw.githubusercontent.com 호출에 붙일 Authorization 헤더."""
    headers = {"User-Agent": "screening-app"}
    tok = _get_auth_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return headers


def has_auth_token() -> bool:
    """UI 가 사이드바에서 '토큰 미설정' 경고를 띄울지 결정."""
    return bool(_get_auth_token())


def _apply_remote(tmp_remote: Path) -> tuple[str, int]:
    """다운로드한 원격 DB(`tmp_remote`)를 로컬 `DB_PATH` 에 반영.

    로컬 DB 가 없으면 → rename (원자 교체).
    로컬 DB 가 있으면 → SQLite ATTACH + INSERT OR REPLACE 로 **merge**.
        - PK 충돌 시 원격이 우선 (정기 갱신이므로 더 최신).
        - 로컬에만 있는 row 는 보존 (예: 다른 시장 데이터, 메타 등).

    Returns:
        (mode, merged_rows_total) — mode ∈ {"replaced", "merged"}.
    """
    import sqlite3

    # SQLite 가 열고 있을 수도 있는 사이드카 정리 (DB 가 일관 상태가 아닐 수 있음)
    for sidecar in (
        DB_PATH.with_suffix(DB_PATH.suffix + "-wal"),
        DB_PATH.with_suffix(DB_PATH.suffix + "-shm"),
    ):
        try:
            sidecar.unlink()
        except OSError:
            pass

    if not DB_PATH.exists():
        os.replace(tmp_remote, DB_PATH)
        return ("replaced", 0)

    # ── merge 경로 ──
    # 1) 임시 위치에 백업 (실패 시 롤백용)
    backup = DB_PATH.with_suffix(DB_PATH.suffix + ".bak")
    try:
        if backup.exists():
            backup.unlink()
        # 원본을 백업으로 옮김
        os.replace(DB_PATH, backup)
        # 로컬 DB 자리는 비어있게 됨 → 원격을 일단 그 자리에 둠
        os.replace(tmp_remote, DB_PATH)

        # 이제 DB_PATH = 원격, backup = 로컬-기존
        # 로컬-기존의 row 를 원격(현재 DB_PATH)에 추가하되, 이미 있으면 원격 유지
        conn = sqlite3.connect(str(DB_PATH))
        try:
            conn.execute("ATTACH DATABASE ? AS oldlocal", (str(backup),))
            cur = conn.execute(
                "SELECT name FROM oldlocal.sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            tables = [r[0] for r in cur.fetchall()]
            merged_rows = 0
            for t in tables:
                # 원격에 없는 row 만 채워넣기 (원격 우선)
                cur = conn.execute(
                    f"INSERT OR IGNORE INTO main.{t} SELECT * FROM oldlocal.{t}"
                )
                merged_rows += cur.rowcount or 0
            conn.commit()
            conn.execute("DETACH DATABASE oldlocal")
        finally:
            conn.close()
    except Exception:
        # 롤백 — 원본 복원, 받은 원격은 폐기
        try:
            if DB_PATH.exists():
                DB_PATH.unlink()
        except OSError:
            pass
        if backup.exists():
            os.replace(backup, DB_PATH)
        raise

    # 성공 — 백업 정리
    try:
        backup.unlink()
    except OSError:
        pass
    return ("merged", merged_rows)


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

    headers = _auth_headers()
    has_token = "Authorization" in headers

    # 1) 원격 stamp 받기
    try:
        r = requests.get(_stamp_url(), timeout=_STAMP_TIMEOUT, headers=headers)
    except Exception as e:
        return SyncResult(status="unreachable", error=str(e))

    # private 레포에 토큰 없으면 404 떨어짐 — 사용자에게 명확히 안내
    if r.status_code == 404:
        if not has_token:
            return SyncResult(
                status="auth_required",
                error="private 레포라면 PAT 토큰이 필요합니다. docs/auto-refresh-setup.md 참고.",
            )
        return SyncResult(status="no_remote")
    if r.status_code in (401, 403):
        return SyncResult(
            status="auth_required",
            error=f"HTTP {r.status_code} — 토큰 권한 부족 / 만료. PAT 재발급 필요.",
        )
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

    # 2) DB 받기 — .db.gz 우선, legacy .db 폴백
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DB_PATH.with_suffix(DB_PATH.suffix + ".tmp")
    try:
        n, fetch_status = _fetch_db_via_requests(tmp, headers, requests)
    except Exception as e:
        return SyncResult(status="error", remote_stamp=remote_stamp, error=str(e))

    if fetch_status == "no_remote":
        return SyncResult(status="no_remote", remote_stamp=remote_stamp)
    if fetch_status == "auth_required":
        return SyncResult(
            status="auth_required", remote_stamp=remote_stamp,
            error="토큰 권한 부족 / private 레포 권한 만료.",
        )
    if fetch_status is not None:
        return SyncResult(status="unreachable", remote_stamp=remote_stamp, error=fetch_status)

    try:
        _apply_remote(tmp)
    except Exception as e:
        return SyncResult(status="error", remote_stamp=remote_stamp, error=str(e))

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

    headers = _auth_headers()
    has_token = "Authorization" in headers

    try:
        req = Request(_stamp_url(), headers=headers)
        with urlopen(req, timeout=_STAMP_TIMEOUT) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        if e.code == 404:
            if not has_token:
                return SyncResult(
                    status="auth_required",
                    error="private 레포라면 PAT 필요. docs/auto-refresh-setup.md 참고.",
                )
            return SyncResult(status="no_remote")
        if e.code in (401, 403):
            return SyncResult(status="auth_required", error=f"HTTP {e.code}")
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

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DB_PATH.with_suffix(DB_PATH.suffix + ".tmp")
    try:
        n, fetch_status = _fetch_db_via_urllib(tmp, headers)
    except Exception as e:
        return SyncResult(status="error", remote_stamp=remote_stamp, error=str(e))

    if fetch_status == "no_remote":
        return SyncResult(status="no_remote", remote_stamp=remote_stamp)
    if fetch_status == "auth_required":
        return SyncResult(status="auth_required", remote_stamp=remote_stamp, error=fetch_status)
    if fetch_status is not None:
        return SyncResult(status="unreachable", remote_stamp=remote_stamp, error=fetch_status)

    try:
        _apply_remote(tmp)
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
