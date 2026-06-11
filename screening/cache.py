"""SQLite 캐시 계층 — 일일 시세/메타데이터 영속 저장.

매매일지(`trading_journal.db`)와 **분리된 DB 파일** 사용: `screening_cache.db`.
통합 시에도 DB 파일은 분리 유지 권장.

스키마:
    prices (ticker, date, open, high, low, close, volume, traded_value)
        PK: (ticker, date)
        - traded_value = close × volume (미국 USD / 한국 KRW 거래대금)
    metadata (ticker, name_en, name_kr, sector, country, exchange,
              market_cap, is_china, is_risk, caution_flags, updated_at)
        PK: ticker
    index_prices (index_code, date, close)
        PK: (index_code, date)

이 모듈은 **순수 SQLite 영속 저장소**이다.
    - `streamlit` import 금지 (`@st.cache_data` 는 상위 UI 레이어에서 부착)
    - 외부 API 호출 금지 (배치 오케스트레이션은 `screening/batch.py`)
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd


# ---------------------------------------------------------------------------
# DB 경로
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH: Path = _PROJECT_ROOT / "screening_cache.db"


def _db_path() -> str:
    """SQLite 가 받아갈 문자열 경로. (Windows 경로 안전)"""
    return str(DB_PATH)


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """짧게 쓰고 닫는 커넥션 컨텍스트."""
    conn = sqlite3.connect(_db_path())
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        # 미국/한국 새로고침이 동시에 돌 때 쓰기 락 경합을 견디도록 대기시간 확보
        conn.execute("PRAGMA busy_timeout=30000")
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 스키마
# ---------------------------------------------------------------------------

_DDL_PRICES = """
CREATE TABLE IF NOT EXISTS prices (
    ticker       TEXT NOT NULL,
    date         TEXT NOT NULL,
    open         REAL,
    high         REAL,
    low          REAL,
    close        REAL,
    volume       REAL,
    traded_value REAL,
    PRIMARY KEY (ticker, date)
)
"""

_DDL_METADATA = """
CREATE TABLE IF NOT EXISTS metadata (
    ticker     TEXT PRIMARY KEY,
    name_en    TEXT,
    name_kr    TEXT,
    sector     TEXT,
    country    TEXT,
    exchange   TEXT,
    market_cap REAL,
    is_china   INTEGER,
    is_risk    INTEGER,
    caution_flags TEXT,
    updated_at TEXT
)
"""

_DDL_INDEX_PRICES = """
CREATE TABLE IF NOT EXISTS index_prices (
    index_code TEXT NOT NULL,
    date       TEXT NOT NULL,
    close      REAL,
    PRIMARY KEY (index_code, date)
)
"""

# 지수별 구성종목(유니버스) 목록. 갱신 시 FDR 에서 받아 저장해두고,
# 화면 로드 때는 외부 호출 없이 여기서 읽는다 (네트워크 구간 제거).
_DDL_UNIVERSE = """
CREATE TABLE IF NOT EXISTS universe (
    index_code TEXT NOT NULL,
    ticker     TEXT NOT NULL,
    updated_at TEXT,
    PRIMARY KEY (index_code, ticker)
)
"""

# 화면 진입 때마다 원시 일봉을 다시 집계하지 않도록 저장하는 표시용 스냅샷.
_DDL_SCREENING_METRICS = """
CREATE TABLE IF NOT EXISTS screening_metrics (
    ticker                 TEXT PRIMARY KEY,
    as_of_date             TEXT,
    last_price             REAL,
    avg_traded_value_20d   REAL,
    max_daily_range_20d    REAL,
    recent_atr_drop_mult   REAL,
    rs_weighted            REAL,
    below_ma5              INTEGER
)
"""

_DDL_STOCK_RETURNS = """
CREATE TABLE IF NOT EXISTS stock_returns (
    ticker    TEXT NOT NULL,
    period    INTEGER NOT NULL,
    return_n  REAL,
    PRIMARY KEY (ticker, period)
)
"""

_DDL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date)",
    "CREATE INDEX IF NOT EXISTS idx_index_prices_date ON index_prices(date)",
    "CREATE INDEX IF NOT EXISTS idx_stock_returns_period ON stock_returns(period)",
]


def init_cache() -> None:
    """SQLite 캐시 DB 초기화 (테이블 없으면 생성 + 구 스키마 마이그레이션)."""
    with _connect() as conn:
        conn.execute(_DDL_PRICES)
        conn.execute(_DDL_METADATA)
        conn.execute(_DDL_INDEX_PRICES)
        conn.execute(_DDL_UNIVERSE)
        conn.execute(_DDL_SCREENING_METRICS)
        conn.execute(_DDL_STOCK_RETURNS)
        for ddl in _DDL_INDEXES:
            conn.execute(ddl)
        _migrate_dollar_volume_column(conn)
        _migrate_caution_flags_column(conn)


def _migrate_dollar_volume_column(conn: sqlite3.Connection) -> None:
    """구 컬럼명 `dollar_volume` → `traded_value` 일회성 리네임.

    원격 동기화로 들어오는 구 스키마 DB(워크플로우 갱신 전)도 처리하도록
    `init_cache()` 매 호출 시 검사. 신규 DB 는 이미 새 컬럼명이라 noop.
    SQLite 3.25+ RENAME COLUMN 사용 (Python 3.7+ 표준 동봉 SQLite 충족).
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(prices)").fetchall()}
    if "dollar_volume" in cols and "traded_value" not in cols:
        conn.execute("ALTER TABLE prices RENAME COLUMN dollar_volume TO traded_value")


def _migrate_caution_flags_column(conn: sqlite3.Connection) -> None:
    """metadata.caution_flags 컬럼이 없으면 추가 (구 DB / 원격 동기 DB 대응)."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(metadata)").fetchall()}
    if "caution_flags" not in cols:
        conn.execute("ALTER TABLE metadata ADD COLUMN caution_flags TEXT")


# ---------------------------------------------------------------------------
# 내부 유틸
# ---------------------------------------------------------------------------

def _normalize_date_index(df: pd.DataFrame) -> pd.DataFrame:
    """index 를 `YYYY-MM-DD` 문자열로 재설정 (SQLite 저장용)."""
    if df is None or df.empty:
        return df
    out = df.copy()
    idx = pd.to_datetime(out.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    out.index = idx.strftime("%Y-%m-%d")
    return out


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# 시세 (prices)
# ---------------------------------------------------------------------------

def cache_save_prices(ticker: str, df: pd.DataFrame) -> None:
    """시세 upsert. `traded_value = close * volume` 자동 계산 (USD/KRW 거래대금).

    Args:
        ticker: 종목 티커 (대문자로 정규화).
        df: `us_load_prices()` 반환 형태. index=date, columns=[Open, High, Low, Close, Volume].
            빈 DF 이면 noop.
    """
    if df is None or df.empty:
        return

    t = ticker.strip().upper()
    norm = _normalize_date_index(df)

    # 컬럼 방어: 없으면 NaN. to_numeric 으로 안전 변환 (변환 실패 시 NaN).
    def col(name: str) -> pd.Series:
        if name not in norm.columns:
            return pd.Series([float("nan")] * len(norm), index=norm.index, dtype=float)
        return pd.to_numeric(norm[name], errors="coerce")

    close = col("Close")
    volume = col("Volume")
    traded_value = close * volume

    rows = [
        (
            t,
            str(date_str),
            None if pd.isna(o) else float(o),
            None if pd.isna(h) else float(h),
            None if pd.isna(l) else float(l),
            None if pd.isna(c) else float(c),
            None if pd.isna(v) else float(v),
            None if pd.isna(tv) else float(tv),
        )
        for date_str, o, h, l, c, v, tv in zip(
            norm.index, col("Open"), col("High"), col("Low"),
            close, volume, traded_value,
        )
    ]

    sql = (
        "INSERT OR REPLACE INTO prices "
        "(ticker, date, open, high, low, close, volume, traded_value) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )
    with _connect() as conn:
        conn.executemany(sql, rows)


_PRICE_COLS = ["Open", "High", "Low", "Close", "Volume", "traded_value"]


def _repair_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """0/결측 OHL 행을 같은 행 Close 로 보정.

    FDR 한국 데이터에서 거래 없는 날 등에 Open/High/Low 가 0(또는 결측)으로
    들어오는 경우가 있다. 그대로 두면 차트가 0에서 솟는 거대 캔들을 그리고
    ATR(True Range)이 폭주한다. Close 는 항상 유효하므로 0/결측 OHL 을 Close
    로 채워 doji(평평한 봉)로 만든다. Close 만 쓰는 RS/거래대금에는 영향 없음.
    """
    if df.empty or "Close" not in df.columns:
        return df
    close = df["Close"]
    for col in ("Open", "High", "Low"):
        if col in df.columns:
            bad = df[col].isna() | (df[col] <= 0)
            if bad.any():
                df.loc[bad, col] = close[bad]
    return df


def cache_load_prices(ticker: str, days: int | None = None) -> pd.DataFrame:
    """시세 조회.

    Args:
        ticker: 종목 티커.
        days: 최근 N영업일만 반환. None 이면 전체.

    Returns:
        index=DatetimeIndex, columns=[Open, High, Low, Close, Volume, traded_value] DataFrame.
        데이터 없으면 빈 DF.
    """
    t = ticker.strip().upper()
    with _connect() as conn:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume, traded_value "
            "FROM prices WHERE ticker = ? ORDER BY date ASC",
            conn,
            params=(t,),
        )

    if df.empty:
        return pd.DataFrame(columns=_PRICE_COLS)

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )
    df = _repair_ohlc(df)
    if days is not None and days > 0:
        df = df.tail(days)
    return df


def cache_load_prices_bulk(
    tickers: Iterable[str], days: int | None = None
) -> dict[str, pd.DataFrame]:
    """여러 티커의 시세를 **쿼리 1회**로 일괄 조회.

    종목별 `cache_load_prices` 를 수천 번 호출하면 커넥션 open/close + 쿼리
    왕복 오버헤드가 누적돼 전 종목 스크리닝이 수십 초~수 분 걸린다. 이 함수는
    윈도우 함수(ROW_NUMBER)로 종목별 최근 `days` 행을 한 방에 가져와 pandas
    groupby 로 분리한다 (≈20배 빠름).

    Args:
        tickers: 대상 티커. 정규화(대문자) 후 이 집합에 속한 것만 반환.
        days: 종목별 최근 N영업일. None 이면 전체.

    Returns:
        {ticker(대문자): DataFrame}. 데이터 없는 티커는 키 부재.
        각 DataFrame 은 `cache_load_prices` 와 동일 형식(OHLC 보정 포함).
    """
    tset = {str(t).strip().upper() for t in tickers if t and str(t).strip()}
    if not tset:
        return {}

    with _connect() as conn:
        # 원하는 티커만 임시테이블에 담아 JOIN — 윈도우 함수를 전체 테이블이 아닌
        # 대상 종목으로만 좁힌다 (IN 절 파라미터 한계도 회피).
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS _wanted (ticker TEXT PRIMARY KEY)")
        conn.execute("DELETE FROM _wanted")
        conn.executemany(
            "INSERT OR IGNORE INTO _wanted (ticker) VALUES (?)",
            [(t,) for t in tset],
        )
        if days is not None and days > 0:
            sql = (
                "SELECT ticker, date, open, high, low, close, volume, traded_value FROM ("
                "  SELECT p.ticker, p.date, p.open, p.high, p.low, p.close, "
                "         p.volume, p.traded_value, "
                "         ROW_NUMBER() OVER (PARTITION BY p.ticker ORDER BY p.date DESC) AS rn "
                "  FROM prices p JOIN _wanted w ON p.ticker = w.ticker"
                ") WHERE rn <= ? ORDER BY ticker ASC, date ASC"
            )
            df = pd.read_sql_query(sql, conn, params=(int(days),))
        else:
            df = pd.read_sql_query(
                "SELECT p.ticker, p.date, p.open, p.high, p.low, p.close, "
                "p.volume, p.traded_value "
                "FROM prices p JOIN _wanted w ON p.ticker = w.ticker "
                "ORDER BY p.ticker ASC, p.date ASC",
                conn,
            )

    if df.empty:
        return {}

    df["date"] = pd.to_datetime(df["date"])
    df = df.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )

    out: dict[str, pd.DataFrame] = {}
    for tk, g in df.groupby("ticker", sort=False):
        g = g.drop(columns=["ticker"]).set_index("date").sort_index()
        out[str(tk)] = _repair_ohlc(g[_PRICE_COLS])
    return out


def cache_save_computed_snapshot(
    metrics: pd.DataFrame,
    returns: pd.DataFrame,
    target_tickers: Iterable[str],
) -> None:
    """화면 표시용 종목 지표와 기간별 수익률을 원자적으로 교체 저장."""
    targets = {
        str(t).strip().upper() for t in target_tickers if t and str(t).strip()
    }
    if not targets:
        return

    metric_rows = []
    if metrics is not None and not metrics.empty:
        for ticker, row in metrics.iterrows():
            metric_rows.append(
                (
                    str(ticker).strip().upper(),
                    row.get("as_of_date"),
                    row.get("last_price"),
                    row.get("avg_traded_value_20d"),
                    row.get("max_daily_range_20d"),
                    row.get("recent_atr_drop_mult"),
                    row.get("rs_weighted"),
                    1 if row.get("below_ma5") else 0,
                )
            )

    return_rows = []
    if returns is not None and not returns.empty:
        for row in returns.itertuples(index=False):
            return_rows.append(
                (str(row.ticker).strip().upper(), int(row.period), float(row.return_n))
            )

    with _connect() as conn:
        conn.execute(_DDL_SCREENING_METRICS)
        conn.execute(_DDL_STOCK_RETURNS)
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS _snapshot_targets (ticker TEXT PRIMARY KEY)")
        conn.execute("DELETE FROM _snapshot_targets")
        conn.executemany(
            "INSERT OR IGNORE INTO _snapshot_targets (ticker) VALUES (?)",
            [(t,) for t in targets],
        )
        conn.execute(
            "DELETE FROM screening_metrics WHERE ticker IN "
            "(SELECT ticker FROM _snapshot_targets)"
        )
        conn.execute(
            "DELETE FROM stock_returns WHERE ticker IN "
            "(SELECT ticker FROM _snapshot_targets)"
        )
        if metric_rows:
            conn.executemany(
                "INSERT INTO screening_metrics "
                "(ticker, as_of_date, last_price, avg_traded_value_20d, "
                "max_daily_range_20d, recent_atr_drop_mult, rs_weighted, below_ma5) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                metric_rows,
            )
        if return_rows:
            conn.executemany(
                "INSERT INTO stock_returns (ticker, period, return_n) VALUES (?, ?, ?)",
                return_rows,
            )


def cache_load_computed_metrics(tickers: Iterable[str]) -> pd.DataFrame:
    """저장된 표시용 종목 지표를 일괄 조회."""
    tset = {str(t).strip().upper() for t in tickers if t and str(t).strip()}
    if not tset:
        return pd.DataFrame()
    with _connect() as conn:
        try:
            rows = conn.execute(
                "SELECT ticker, as_of_date, last_price, avg_traded_value_20d, "
                "max_daily_range_20d, recent_atr_drop_mult, rs_weighted, below_ma5 "
                "FROM screening_metrics"
            ).fetchall()
        except sqlite3.OperationalError:
            return pd.DataFrame()
    rows = [r for r in rows if str(r[0]) in tset]
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        rows,
        columns=[
            "ticker", "as_of_date", "last_price", "avg_traded_value_20d",
            "max_daily_range_20d", "recent_atr_drop_mult", "rs_weighted", "below_ma5",
        ],
    ).set_index("ticker")


def cache_load_stock_returns(tickers: Iterable[str], period: int) -> pd.Series:
    """저장된 N일 수익률을 티커 인덱스 Series 로 조회."""
    tset = {str(t).strip().upper() for t in tickers if t and str(t).strip()}
    if not tset:
        return pd.Series(dtype=float)
    with _connect() as conn:
        try:
            rows = conn.execute(
                "SELECT ticker, return_n FROM stock_returns WHERE period = ?",
                (int(period),),
            ).fetchall()
        except sqlite3.OperationalError:
            return pd.Series(dtype=float)
    values = {str(t): float(v) for t, v in rows if str(t) in tset and v is not None}
    return pd.Series(values, dtype=float)


def cache_delete_prices(ticker: str) -> int:
    """해당 티커의 모든 시세 행 삭제. 분할/스핀오프 발생 시 옛 가격이
    미조정 상태로 남아 점프가 생기지 않도록 통째로 갈아엎을 때 사용.

    Returns:
        삭제된 행 수.
    """
    t = ticker.strip().upper()
    with _connect() as conn:
        cur = conn.execute("DELETE FROM prices WHERE ticker = ?", (t,))
        return int(cur.rowcount or 0)


def cache_get_last_price_date(ticker: str) -> str | None:
    """해당 티커의 마지막 저장된 날짜(`YYYY-MM-DD`). 없으면 None."""
    t = ticker.strip().upper()
    with _connect() as conn:
        row = conn.execute(
            "SELECT MAX(date) FROM prices WHERE ticker = ?", (t,)
        ).fetchone()
    if row is None or row[0] is None:
        return None
    return str(row[0])


def cache_get_all_last_price_dates() -> dict[str, str]:
    """모든 티커 → 마지막 저장일(`YYYY-MM-DD`) 딕셔너리.

    배치 새로고침에서 'stale 우선' 정렬용. 한 번의 SQL로 모든 티커 일괄 조회.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT ticker, MAX(date) FROM prices GROUP BY ticker"
        ).fetchall()
    return {str(t): str(d) for t, d in rows if d is not None}


# ---------------------------------------------------------------------------
# 유니버스 (지수별 구성종목 목록)
# ---------------------------------------------------------------------------

def cache_save_universe(index_code: str, tickers: Iterable[str]) -> int:
    """지수 구성종목 목록을 통째로 교체 저장 (해당 index_code 의 기존 행 삭제 후 삽입).

    Args:
        index_code: 지수 코드 (예: "^IXIC", "KS11").
        tickers: 구성종목 티커 리스트. 대문자/공백 정규화.

    Returns:
        저장된 티커 수.
    """
    code = str(index_code).strip()
    norm = []
    seen: set[str] = set()
    for t in tickers:
        if not t or not str(t).strip():
            continue
        u = str(t).strip().upper()
        if u in seen:
            continue
        seen.add(u)
        norm.append(u)
    updated_at = _utc_now_iso()
    with _connect() as conn:
        conn.execute("DELETE FROM universe WHERE index_code = ?", (code,))
        if norm:
            conn.executemany(
                "INSERT OR REPLACE INTO universe (index_code, ticker, updated_at) "
                "VALUES (?, ?, ?)",
                [(code, t, updated_at) for t in norm],
            )
    return len(norm)


def cache_load_universe(index_code: str) -> list[str]:
    """지수 구성종목 목록 조회. 저장된 게 없으면 빈 리스트."""
    code = str(index_code).strip()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT ticker FROM universe WHERE index_code = ? ORDER BY ticker ASC",
            (code,),
        ).fetchall()
    return [str(r[0]) for r in rows]


def cache_prune_orphan_prices(vacuum: bool = False) -> int:
    """현재 유니버스(어느 지수에도) 속하지 않은 티커의 시세 행을 삭제.

    상장폐지·지수 편출 등으로 더는 스크리닝 대상이 아닌 종목의 옛 시세가
    `prices` 에 무한정 쌓이는 것을 막는다. **날짜 트리밍은 하지 않는다**
    (장기 차트를 위해 전체 기간 누적 유지).

    안전장치: `universe` 테이블이 비어 있으면(아직 한 번도 저장 안 됨) 아무것도
    삭제하지 않는다 — 전체 시세가 통째로 날아가는 사고 방지.

    Args:
        vacuum: True 면 삭제 후 VACUUM 으로 파일 크기까지 회수
            (느림, 클라우드 갱신/일회성 청소에만 사용 권장).

    Returns:
        삭제된 시세 행 수.
    """
    with _connect() as conn:
        u_count = conn.execute("SELECT COUNT(*) FROM universe").fetchone()[0]
        if not u_count:
            return 0
        cur = conn.execute(
            "DELETE FROM prices WHERE ticker NOT IN (SELECT ticker FROM universe)"
        )
        deleted = int(cur.rowcount or 0)
    if vacuum and deleted:
        # VACUUM 은 트랜잭션 밖에서 단독 실행해야 함
        conn2 = sqlite3.connect(_db_path())
        try:
            conn2.execute("VACUUM")
        finally:
            conn2.close()
    return deleted


# ---------------------------------------------------------------------------
# 메타데이터
# ---------------------------------------------------------------------------

_META_FIELDS = (
    "name_en",
    "name_kr",
    "sector",
    "country",
    "exchange",
    "market_cap",
    "is_china",
    "is_risk",
)


def cache_save_meta(ticker: str, meta: dict) -> None:
    """메타데이터 upsert. `updated_at` 현재 UTC 시각 기록."""
    if not meta:
        return
    t = ticker.strip().upper()
    updated_at = _utc_now_iso()

    def _bool_to_int(v) -> int | None:
        if v is None:
            return None
        return 1 if v else 0

    row = (
        t,
        meta.get("name_en"),
        meta.get("name_kr"),
        meta.get("sector"),
        meta.get("country"),
        meta.get("exchange"),
        float(meta["market_cap"]) if meta.get("market_cap") not in (None, "") else None,
        _bool_to_int(meta.get("is_china")),
        _bool_to_int(meta.get("is_risk")),
        meta.get("caution_flags"),
        updated_at,
    )

    sql = (
        "INSERT OR REPLACE INTO metadata "
        "(ticker, name_en, name_kr, sector, country, exchange, "
        "market_cap, is_china, is_risk, caution_flags, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    with _connect() as conn:
        conn.execute(sql, row)


def cache_load_meta(ticker: str) -> dict | None:
    """메타 조회. 없으면 None."""
    t = ticker.strip().upper()
    with _connect() as conn:
        row = conn.execute(
            "SELECT name_en, name_kr, sector, country, exchange, "
            "market_cap, is_china, is_risk, caution_flags, updated_at "
            "FROM metadata WHERE ticker = ?",
            (t,),
        ).fetchone()
    if row is None:
        return None
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


def update_risk_flags(flags: dict) -> None:
    """메타 TTL과 무관하게 is_risk / caution_flags 두 컬럼만 갱신.

    flags: { code: {"is_risk": bool, "labels": list[str]} }
    - metadata 행이 이미 있는 코드만 UPDATE (행 생성은 메타 갱신 담당).
    - flags 에 없는 모든 종목은 두 컬럼을 클리어(0/NULL)해 지정 해제를 반영.
    """
    with _connect() as conn:
        existing = {r[0] for r in conn.execute("SELECT ticker FROM metadata").fetchall()}
        # 한국 6자리 숫자 티커만 클리어 — 같은 metadata 테이블의 미국 종목 is_risk 보존
        conn.execute(
            "UPDATE metadata SET is_risk = 0, caution_flags = NULL "
            "WHERE ticker GLOB '[0-9][0-9][0-9][0-9][0-9][0-9]'"
        )
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


def cache_load_meta_bulk(tickers: Iterable[str]) -> dict[str, dict]:
    """여러 티커의 메타를 **쿼리 1회**로 일괄 조회. 형식은 `cache_load_meta` 와 동일."""
    tset = {str(t).strip().upper() for t in tickers if t and str(t).strip()}
    if not tset:
        return {}
    _SQL = (
        "SELECT ticker, name_en, name_kr, sector, country, exchange, "
        "market_cap, is_china, is_risk, caution_flags, updated_at FROM metadata"
    )
    with _connect() as conn:
        try:
            rows = conn.execute(_SQL).fetchall()
        except sqlite3.OperationalError:
            # 원격 동기화 DB에 caution_flags 컬럼이 없는 경우 마이그레이션 후 재시도
            _migrate_caution_flags_column(conn)
            rows = conn.execute(_SQL).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        tk = str(r[0])
        if tk not in tset:
            continue
        out[tk] = {
            "name_en": r[1],
            "name_kr": r[2],
            "sector": r[3],
            "country": r[4],
            "exchange": r[5],
            "market_cap": r[6],
            "is_china": bool(r[7]) if r[7] is not None else None,
            "is_risk": bool(r[8]) if r[8] is not None else None,
            "caution_flags": r[9],
            "updated_at": r[10],
        }
    return out


def cache_meta_age_days(ticker: str) -> int | None:
    """메타의 `updated_at` 기준 경과 일수. 없으면 None."""
    m = cache_load_meta(ticker)
    if not m or not m.get("updated_at"):
        return None
    try:
        ts = datetime.strptime(m["updated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None
    delta = datetime.now(timezone.utc) - ts
    return max(0, delta.days)


# ---------------------------------------------------------------------------
# 지수
# ---------------------------------------------------------------------------

def cache_save_index(index_code: str, df: pd.DataFrame) -> None:
    """지수 일봉 upsert (Close 만 저장)."""
    if df is None or df.empty:
        return
    code = index_code.strip()
    norm = _normalize_date_index(df)
    close = norm["Close"] if "Close" in norm.columns else pd.Series(dtype=float)

    rows = [
        (code, str(d), None if pd.isna(c) else float(c))
        for d, c in zip(norm.index, close)
    ]
    with _connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO index_prices (index_code, date, close) VALUES (?, ?, ?)",
            rows,
        )


def cache_load_index(index_code: str, days: int | None = None) -> pd.DataFrame:
    """지수 일봉 조회. 반환 DataFrame 의 컬럼은 `Close` 하나."""
    code = index_code.strip()
    with _connect() as conn:
        df = pd.read_sql_query(
            "SELECT date, close FROM index_prices WHERE index_code = ? ORDER BY date ASC",
            conn,
            params=(code,),
        )

    if df.empty:
        return pd.DataFrame(columns=["Close"])

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df.rename(columns={"close": "Close"})
    if days is not None and days > 0:
        df = df.tail(days)
    return df


def cache_get_last_index_date(index_code: str) -> str | None:
    """지수 마지막 저장일."""
    code = index_code.strip()
    with _connect() as conn:
        row = conn.execute(
            "SELECT MAX(date) FROM index_prices WHERE index_code = ?", (code,)
        ).fetchone()
    if row is None or row[0] is None:
        return None
    return str(row[0])
