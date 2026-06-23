"""Print a backend sector RS snapshot.

Usage:
    python scripts/show_sector_rs.py --index-code KS11 --period 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from screening.sector import (  # noqa: E402
    screen_build_sector_snapshot,
    screen_select_sector_members,
    screen_select_sector_summary,
)


def _pct(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value) * 100:.2f}%"


def _num(value: object, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):,.{digits}f}"


def _print_sector(snapshot: dict, sector: str, top_members: int) -> None:
    summary = screen_select_sector_summary(snapshot["sector_summary"], sector)
    members = screen_select_sector_members(
        snapshot["sector_members"], sector, top_n=top_members
    )

    print(f"\nSector: {sector}")
    if summary.empty:
        print("No matching sector summary row.")
    else:
        row = summary.iloc[0]
        print(
            "Summary: "
            f"rank={int(row['rank'])}, "
            f"score={_pct(row['sector_score'])}, "
            f"positive={_pct(row['positive_ratio'])}, "
            f"stocks={int(row['stock_count']):,}, "
            f"top={row['top_ticker']} {row['top_name']}"
        )

    if members.empty:
        print("No matching sector members.")
        return

    print("Members")
    for member in members.itertuples(index=False):
        name = member.name_kr or member.name_en or ""
        print(
            f"  {int(member.rank_in_sector):>2}. {member.ticker} {name} "
            f"return={_pct(member.return_n)} "
            f"rs={_num(member.rs, 4)} "
            f"weighted={_num(member.rs_weighted, 4)}"
        )


def _print_summary(
    snapshot: dict,
    top_sectors: int,
    top_members: int,
    *,
    sector: str | None = None,
) -> None:
    summary = snapshot["sector_summary"]
    members = snapshot["sector_members"]
    stats = snapshot["filter_stats"]

    print(f"Index: {snapshot['index_code']}  Period: {snapshot['period']}d")
    print(
        "Universe: "
        f"{snapshot['input_count']:,}/{snapshot['universe_count']:,} "
        f"({snapshot['universe_source']})"
    )
    print(
        "Filters: "
        f"total={stats.get('total', 0):,}, final={stats.get('final', 0):,}, "
        f"lag_excluded={snapshot['lag_excluded']:,}, ranked={len(snapshot['ranked']):,}"
    )

    if summary.empty:
        print("\nNo sector summary rows.")
        return

    if sector:
        _print_sector(snapshot, sector, top_members)
        return

    print("\nTop sectors")
    for row in summary.head(max(top_sectors, 0)).itertuples(index=False):
        print(
            f"{int(row.rank):>2}. {row.sector} "
            f"score={_pct(row.sector_score)} "
            f"positive={_pct(row.positive_ratio)} "
            f"stocks={int(row.stock_count):,} "
            f"top={row.top_ticker} {row.top_name}"
        )
        sector_members = members[members["sector"] == row.sector].head(
            max(top_members, 0)
        )
        for member in sector_members.itertuples(index=False):
            name = member.name_kr or member.name_en or ""
            print(
                f"    {int(member.rank_in_sector):>2}. {member.ticker} {name} "
                f"return={_pct(member.return_n)} "
                f"rs={_num(member.rs, 4)}"
            )


def _save_csv(snapshot: dict, csv_dir: str | None) -> None:
    if not csv_dir:
        return
    out_dir = Path(csv_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    code = snapshot["index_code"].replace("^", "").replace("/", "_")
    summary_path = out_dir / f"{code}_sector_summary.csv"
    members_path = out_dir / f"{code}_sector_members.csv"
    snapshot["sector_summary"].to_csv(summary_path, index=False, encoding="utf-8-sig")
    snapshot["sector_members"].to_csv(members_path, index=False, encoding="utf-8-sig")
    print(f"\nSaved CSV: {summary_path}")
    print(f"Saved CSV: {members_path}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show sector RS leadership snapshot.")
    parser.add_argument("--index-code", required=True, help="^IXIC, ^GSPC, KS11, or KQ11")
    parser.add_argument("--period", type=int, default=20, help="RS period in trading days")
    parser.add_argument("--top-sectors", type=int, default=10, help="Rows to print")
    parser.add_argument(
        "--top-members",
        type=int,
        default=5,
        help="Members per sector to score and print",
    )
    parser.add_argument(
        "--min-sector-size",
        type=int,
        default=1,
        help="Minimum member count for a sector summary row",
    )
    parser.add_argument(
        "--max-tickers",
        type=int,
        default=None,
        help="Limit tickers for quick backend checks",
    )
    parser.add_argument(
        "--sector",
        default=None,
        help="Print only this sector's summary and members",
    )
    parser.add_argument("--csv-dir", default=None, help="Directory for summary/members CSV")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    snapshot = screen_build_sector_snapshot(
        args.index_code,
        period=args.period,
        top_n_per_sector=args.top_members,
        min_sector_size=args.min_sector_size,
        max_tickers=args.max_tickers,
    )
    _print_summary(
        snapshot,
        args.top_sectors,
        args.top_members,
        sector=args.sector,
    )
    _save_csv(snapshot, args.csv_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
