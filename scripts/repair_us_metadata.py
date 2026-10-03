"""과거 정상 DB에서 조회 실패로 손상된 미국 메타만 복원하는 일회성 CLI.

시세·지수·정상 메타·한국 종목은 변경하지 않는다. 복원 후 refresh_cache를
실행해 최신 메타 재조회와 섹터 스냅샷 계산을 진행한다.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3

from screening import cache


def repair_us_metadata(source_db: Path) -> int:
    with sqlite3.connect(source_db.resolve().as_uri() + "?mode=ro", uri=True) as source:
        source.row_factory = sqlite3.Row
        rows = source.execute("SELECT * FROM metadata").fetchall()
    repaired = 0
    for row in rows:
        old = dict(row)
        ticker = old["ticker"]
        if ticker.isdigit() or old.get("name_en") == ticker:
            continue
        if not all(old.get(key) for key in ("name_en", "sector", "country", "exchange")):
            continue
        current = cache.cache_load_meta(ticker)
        if not current or not current.get("is_risk") or current.get("name_en") != ticker:
            continue
        if any(current.get(key) for key in ("sector", "country", "exchange")):
            continue
        # 시총은 최신 fast_info 값이 있을 수 있어 보존한다.
        old["market_cap"] = current.get("market_cap") or old.get("market_cap")
        # 복원 데이터를 최신 조회로 오인해 TTL 동안 skip하지 않도록 한다.
        cache.cache_save_meta(ticker, old)
        with cache._connect() as conn:
            conn.execute("UPDATE metadata SET updated_at=? WHERE ticker=?",
                         ("2000-01-01T00:00:00Z", ticker))
        repaired += 1
    return repaired


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, required=True)
    args = parser.parse_args()
    cache.init_cache()
    print(f"Repaired US metadata: {repair_us_metadata(args.source_db)}")


if __name__ == "__main__":
    main()
