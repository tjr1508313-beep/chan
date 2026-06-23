"""Build or enrich Korean sector mapping from LS Securities industry APIs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from screening.data_kr import kr_save_sector_map  # noqa: E402
from screening.ls_sector import ls_build_sector_map, ls_configured  # noqa: E402


_DEFAULT_MAP = _PROJECT_ROOT / "data" / "kr_sector_map.csv"


def _load_existing(path: Path = _DEFAULT_MAP) -> pd.DataFrame:
    columns = ["ticker", "name_kr", "sector", "source", "updated_at"]
    if not path.exists():
        return pd.DataFrame(columns=columns)
    df = pd.read_csv(path, dtype=str).fillna("")
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    df["ticker"] = df["ticker"].astype(str).str.strip().str.zfill(6)
    return df[columns]


def merge_sector_maps(
    existing: pd.DataFrame,
    candidates: pd.DataFrame,
    *,
    overwrite: bool = False,
) -> pd.DataFrame:
    """Merge LS candidates into existing sector map.

    By default existing rows win, so manual/name-rule corrections are preserved
    and LS fills only previously unmapped tickers.
    """
    cols = ["ticker", "name_kr", "sector", "source", "updated_at"]
    existing_norm = existing.copy() if existing is not None else pd.DataFrame(columns=cols)
    candidates_norm = candidates.copy() if candidates is not None else pd.DataFrame(columns=cols)
    for df in (existing_norm, candidates_norm):
        for col in cols:
            if col not in df.columns:
                df[col] = ""
        df["ticker"] = df["ticker"].astype(str).str.strip().str.zfill(6)
        df["sector"] = df["sector"].fillna("").astype(str).str.strip()

    if overwrite:
        merged = pd.concat([existing_norm[cols], candidates_norm[cols]], ignore_index=True)
        keep = "last"
    else:
        merged = pd.concat([existing_norm[cols], candidates_norm[cols]], ignore_index=True)
        keep = "first"

    merged = merged[(merged["ticker"] != "") & (merged["sector"] != "")]
    return (
        merged.drop_duplicates(subset=["ticker"], keep=keep)
        .sort_values("ticker")
        .reset_index(drop=True)
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build KR sector map from LS industry APIs.")
    parser.add_argument("--apply", action="store_true", help="Write merged rows to data/kr_sector_map.csv")
    parser.add_argument("--overwrite", action="store_true", help="Let LS rows replace existing rows")
    parser.add_argument(
        "--include-krx-theme",
        action="store_true",
        help="Prefer selected KRX theme/sector indices before official industries",
    )
    parser.add_argument(
        "--include-broad",
        action="store_true",
        help="Include broad buckets such as 제조업/KOSDAQ 제조",
    )
    parser.add_argument("--max-industries", type=int, default=None, help="Limit industries for smoke tests")
    parser.add_argument("--sleep-sec", type=float, default=1.05, help="Delay between LS calls")
    parser.add_argument("--preview", type=int, default=40, help="Rows to print")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not ls_configured():
        print("LS_APP_KEY/LS_APP_SECRET이 설정되어 있지 않습니다.")
        return 1

    candidates = ls_build_sector_map(
        include_krx_theme=args.include_krx_theme,
        include_broad=args.include_broad,
        max_industries=args.max_industries,
        sleep_sec=args.sleep_sec,
    )
    existing = _load_existing()
    merged = merge_sector_maps(existing, candidates, overwrite=args.overwrite)

    added = len(set(merged["ticker"]) - set(existing["ticker"]))
    replaced = 0
    if args.overwrite and not existing.empty:
        before = existing.set_index("ticker")["sector"].to_dict()
        after = merged.set_index("ticker")["sector"].to_dict()
        replaced = sum(1 for ticker, sector in before.items() if after.get(ticker) != sector)

    print(f"LS candidates: {len(candidates):,}")
    print(f"Existing rows: {len(existing):,}")
    print(f"Merged rows: {len(merged):,} (added={added:,}, replaced={replaced:,})")
    if not candidates.empty:
        print("\nCandidates preview")
        print(candidates.head(args.preview).to_string(index=False))
    if not merged.empty:
        print("\nMerged preview")
        print(merged.head(args.preview).to_string(index=False))

    if args.apply:
        saved = kr_save_sector_map(merged)
        print(f"\nSaved: data/kr_sector_map.csv ({saved:,} rows)")
    else:
        print("\nPreview only. Add --apply to write data/kr_sector_map.csv.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
