"""헤드리스 캐시 갱신 CLI — GitHub Actions 용.

Streamlit 없이 `screening/batch*.py` 의 갱신 함수를 호출해
`screening_cache.db` 를 업데이트한다.

대상: **지수 + 시세 + 메타데이터** (메타는 TTL 7일 기반 증분 — 보통 일주일에 한 번만 실제 외부 호출).

사용법:
    python -m scripts.refresh_cache --market us
    python -m scripts.refresh_cache --market kr

종료 코드:
    0  — 정상 (실패 종목이 있어도 임계 이하)
    1  — 임계치 초과 실패 / 치명적 예외
    2  — 인자 오류

stdout 마지막 줄에 한 줄 요약을 출력해 GitHub Actions 가 텔레그램으로 전달한다.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

# 패키지 임포트를 위해 프로젝트 루트를 sys.path 에 추가
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from screening import batch, batch_kr, cache  # noqa: E402
from screening.data import us_get_nasdaq_tickers, us_get_sp500_tickers  # noqa: E402
from screening.data_kr import kr_get_kosdaq_tickers, kr_get_kospi_tickers  # noqa: E402


# 갱신 실패 종목 비율이 이 값을 넘으면 워크플로우 실패로 간주
_FAILURE_RATE_THRESHOLD = 0.10  # 10%


def _refresh_us() -> dict:
    """미국주식 지수(^IXIC, ^GSPC) + 나스닥·S&P500 시세 + 메타데이터 갱신."""
    out: dict = {"market": "us", "indexes": {}, "prices": {}, "meta": {}}

    for code in ("^IXIC", "^GSPC"):
        out["indexes"][code] = batch.screen_refresh_index(code, days=300, force=False)

    nasdaq = us_get_nasdaq_tickers()
    sp500 = us_get_sp500_tickers()
    tickers = sorted(set(nasdaq) | set(sp500))
    out["prices"]["target_count"] = len(tickers)
    out["prices"]["result"] = batch.screen_refresh_prices(
        tickers, days=300, force=False, max_workers=4
    )

    # 메타데이터 — TTL 7일 증분 (대다수는 skip, 신규/만료 종목만 yfinance .info 호출)
    out["meta"]["target_count"] = len(tickers)
    out["meta"]["result"] = batch.screen_refresh_meta(
        tickers, ttl_days=7, force=False, max_workers=4
    )
    return out


def _refresh_kr() -> dict:
    """한국주식 지수(KS11, KQ11) + 코스피·코스닥 시세 + 메타데이터 갱신."""
    out: dict = {"market": "kr", "indexes": {}, "prices": {}, "meta": {}}

    for code in ("KS11", "KQ11"):
        out["indexes"][code] = batch_kr.screen_refresh_index_kr(
            code, days=300, force=False
        )

    kospi = kr_get_kospi_tickers()
    kosdaq = kr_get_kosdaq_tickers()
    tickers = sorted(set(kospi) | set(kosdaq))
    out["prices"]["target_count"] = len(tickers)
    out["prices"]["result"] = batch_kr.screen_refresh_prices_kr(
        tickers, days=300, force=False, max_workers=8
    )

    # 메타데이터 — FDR StockListing 한 번 호출로 전체 처리, TTL 7일 증분
    out["meta"]["target_count"] = len(tickers)
    out["meta"]["result"] = batch_kr.screen_refresh_meta_kr(
        tickers, ttl_days=7, force=False
    )
    return out


def _summarize(report: dict, elapsed_s: float) -> tuple[str, bool]:
    """한 줄 요약 + 임계 초과 여부."""
    market = report["market"].upper()
    px = report["prices"]
    total = px.get("target_count", 0)
    result = px.get("result", {})
    updated = int(result.get("updated", 0))
    skipped = int(result.get("skipped", 0))
    failed_list = result.get("failed", []) or []
    failed_cnt = len(failed_list)
    fr = int(result.get("force_refetched", 0))

    idx_fails: list[str] = []
    for code, res in report["indexes"].items():
        if res.get("failed"):
            idx_fails.extend(res["failed"])

    failure_rate = (failed_cnt / total) if total else 0.0
    threshold_exceeded = failure_rate > _FAILURE_RATE_THRESHOLD or bool(idx_fails)

    parts = [
        f"[{market}] 시세 {updated}↑ {skipped}= {failed_cnt}✗",
        f"({failure_rate*100:.1f}% 실패)",
    ]
    if fr:
        parts.append(f"분할재요청 {fr}")
    if idx_fails:
        parts.append(f"지수실패={','.join(idx_fails)}")

    meta = report.get("meta", {})
    meta_result = meta.get("result", {}) if isinstance(meta, dict) else {}
    if meta_result:
        m_up = int(meta_result.get("updated", 0))
        m_skip = int(meta_result.get("skipped", 0))
        m_fail = len(meta_result.get("failed", []) or [])
        parts.append(f"메타 {m_up}↑ {m_skip}= {m_fail}✗")

    parts.append(f"{elapsed_s:.0f}초")
    return " ".join(parts), threshold_exceeded


def main() -> int:
    parser = argparse.ArgumentParser(
        description="screening_cache.db 헤드리스 갱신 (지수+시세+메타, TTL 7일 증분)"
    )
    parser.add_argument("--market", choices=("us", "kr"), required=True)
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="갱신 결과를 JSON으로 기록할 경로 (선택). Actions가 텔레그램에 전달.",
    )
    args = parser.parse_args()

    cache.init_cache()
    t0 = time.time()

    try:
        if args.market == "us":
            report = _refresh_us()
        else:
            report = _refresh_kr()
    except Exception as e:
        elapsed = time.time() - t0
        err = f"[{args.market.upper()}] 치명적 예외: {e}"
        print(err)
        traceback.print_exc(file=sys.stderr)
        if args.json_out:
            args.json_out.write_text(
                json.dumps(
                    {"market": args.market, "fatal": str(e), "elapsed_s": elapsed},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
        print(err)  # 마지막 줄(요약) 위치
        return 1

    elapsed = time.time() - t0
    summary, exceeded = _summarize(report, elapsed)

    if args.json_out:
        args.json_out.write_text(
            json.dumps(
                {"summary": summary, "elapsed_s": elapsed, "report": report},
                ensure_ascii=False, indent=2, default=str,
            ),
            encoding="utf-8",
        )

    print(summary)  # 마지막 줄 — Actions가 grep 으로 캡처
    return 1 if exceeded else 0


if __name__ == "__main__":
    sys.exit(main())
