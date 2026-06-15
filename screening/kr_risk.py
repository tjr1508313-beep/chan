"""한국주식 관리종목·투자주의환기 지정 조회 (FDR KRX 캐시 기반).

FDR의 fdr.StockListing('KRX') 결과에서 Dept 컬럼을 읽어 지정 종목을 분류한다.
Streamlit Cloud에서도 작동 (KRX GitHub 캐시 경유 → IP 차단 없음).

is_risk = True  ⟸ 관리종목  (Dept에 "관리종목" 포함)
labels         = 표시용 배지 텍스트

거래정지·정리매매:
    Volume=0 → 거래대금 300억 필터에서 자동 제거 → 별도 처리 불필요.

투자주의환기종목:
    is_risk=False, labels=["투자주의환기"] 로만 표시.

LS증권 OpenAPI 방식 비교:
    t1404/t1405 TR은 관리종목 필터가 아닌 전체 종목 리스트를 반환함이 확인됨
    (2026-06-15 실증) → FDR Dept 컬럼 방식으로 대체.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_RISK_DEPT_KEYWORDS = ("관리종목",)
_CAUTION_DEPT_KEYWORDS = ("투자주의환기종목",)


def kr_fetch_risk_flags() -> dict[str, dict]:
    """FDR StockListing KRX 전체에서 지정 종목 조회.

    반환: {code6: {"is_risk": bool, "labels": list[str]}}
    실패 시 빈 dict + 경고 로그 (graceful degrade).
    """
    try:
        import FinanceDataReader as fdr  # type: ignore
        df = fdr.StockListing("KRX")
    except Exception as exc:
        logger.warning("FDR StockListing KRX 조회 실패 (%s) — 관리종목 플래그 skip", exc)
        return {}

    if "Dept" not in df.columns or "Code" not in df.columns:
        logger.warning("FDR StockListing KRX에 Dept/Code 컬럼 없음 — 관리종목 플래그 skip")
        return {}

    out: dict[str, dict] = {}
    for _, row in df.iterrows():
        dept = str(row.get("Dept") or "").strip()
        if not dept:
            continue
        code = str(row.get("Code") or "").strip().zfill(6)
        if not code or not code.isdigit():
            continue

        is_risk = any(kw in dept for kw in _RISK_DEPT_KEYWORDS)
        is_caution = any(kw in dept for kw in _CAUTION_DEPT_KEYWORDS)
        if not is_risk and not is_caution:
            continue

        labels: list[str] = []
        if is_risk:
            labels.append("관리종목")
        if is_caution:
            labels.append("투자주의환기")
        out[code] = {"is_risk": is_risk, "labels": labels}

    logger.info("FDR 관리종목 조회 완료: 총 %d개 (is_risk=%d, caution=%d)",
                len(out),
                sum(1 for v in out.values() if v["is_risk"]),
                sum(1 for v in out.values() if not v["is_risk"]))
    return out
