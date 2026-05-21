"""캐시 DB 일회성 정리 — 죽은 티커 시세 삭제 + VACUUM.

현재 4개 지수(나스닥/S&P500/코스피/코스닥)의 구성종목을 외부 소스에서 받아
`universe` 테이블에 저장한 뒤, **현재 유니버스에 없는** 티커의 시세 행을 삭제하고
VACUUM 으로 파일 크기를 회수한다. 날짜 트리밍은 하지 않는다(장기 차트 유지).

평소에는 갱신 파이프라인(refresh_cache.py / 새로고침 워커)이 자동으로 같은 정리를
수행하므로, 이 스크립트는 누적된 기존 DB 를 처음 한 번 청소할 때만 쓰면 된다.

사용법:
    python -m scripts.prune_db_once                # 기본 DB (screening_cache.db)
    python -m scripts.prune_db_once <DB경로>        # 특정 파일 지정
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import screening.cache as cache  # noqa: E402


def main() -> int:
    if len(sys.argv) > 1:
        cache.DB_PATH = Path(sys.argv[1]).resolve()
    print(f"대상 DB: {cache.DB_PATH}")
    cache.init_cache()

    from screening.data import us_get_nasdaq_tickers, us_get_sp500_tickers
    from screening.data_kr import kr_get_kospi_tickers, kr_get_kosdaq_tickers

    sources = {
        "^IXIC": us_get_nasdaq_tickers,
        "^GSPC": us_get_sp500_tickers,
        "KS11": kr_get_kospi_tickers,
        "KQ11": kr_get_kosdaq_tickers,
    }
    for code, fn in sources.items():
        tickers = fn()
        n = cache.cache_save_universe(code, tickers)
        print(f"  universe[{code}] = {n:,} 종목")

    before = cache.DB_PATH.stat().st_size
    deleted = cache.cache_prune_orphan_prices(vacuum=True)
    after = cache.DB_PATH.stat().st_size
    print(f"삭제된 죽은 티커 시세 행: {deleted:,}")
    print(f"파일 크기: {before/1e6:.1f}MB → {after/1e6:.1f}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
