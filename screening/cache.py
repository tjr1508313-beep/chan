"""SQLite 캐시 계층 — 일일 시세/메타데이터 저장.

매매일지(`trading_journal.db`)와 **분리된 DB** 파일 사용: `screening_cache.db`.
통합 시에도 DB 파일은 분리 유지 권장.

스키마 (초안):
    prices (ticker, date, open, high, low, close, volume, dollar_volume)
    metadata (ticker, name_en, name_kr, sector, country, exchange,
              market_cap, is_china, is_risk, updated_at)
    index_prices (index_code, date, close)
    settings (key, value)

Phase 1.3 에서 실제 구현 예정.
"""

from __future__ import annotations

DB_PATH = "screening_cache.db"


def init_cache() -> None:
    """SQLite 캐시 DB를 초기화 (테이블 생성).

    생성 테이블: `prices`, `metadata`, `index_prices`, `settings`.
    이미 존재하면 noop (IF NOT EXISTS).
    """
    raise NotImplementedError
