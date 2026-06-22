"""한국주식 섹터 매핑 CSV 후보 생성기.

FDR가 현재 한국 종목 업종 컬럼을 제공하지 않으므로, 종목명 키워드 기반의
1차 실전 섹터 후보를 만든다. 기본은 미리보기만 하며, `--apply`를 주면
`data/kr_sector_map.csv`에 저장한다.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from screening.data_kr import _apply_universe_filter, kr_save_sector_map  # noqa: E402


# 순서가 중요하다. 더 구체적인 테마를 먼저 둔다.
_SECTOR_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("반도체", ("삼성전자", "SK하이닉스", "한미반도체", "리노공업", "ISC", "HPSP", "주성엔지니어링", "원익IPS", "테스", "유진테크", "이오테크닉스", "동진쎄미켐", "솔브레인", "DB하이텍", "피에스케이", "넥스틴", "와이씨", "하나마이크론", "두산테스나")),
    ("전력기기", ("HD현대일렉트릭", "LS ELECTRIC", "LS에코에너지", "효성중공업", "제룡전기", "일진전기", "대한전선", "가온전선", "대원전선", "산일전기", "비츠로테크")),
    ("조선", ("HD현대중공업", "HD한국조선해양", "한화오션", "삼성중공업", "HD현대미포", "현대미포", "성광벤드", "태광", "하이록코리아", "한국카본", "동성화인텍")),
    ("방산", ("한화에어로스페이스", "현대로템", "LIG넥스원", "한국항공우주", "풍산", "SNT다이내믹스", "코츠테크놀로지", "쎄트렉아이", "빅텍", "퍼스텍")),
    ("바이오", ("삼성바이오로직스", "셀트리온", "HLB", "알테오젠", "유한양행", "리가켐바이오", "에이비엘바이오", "SK바이오팜", "SK바이오사이언스", "한미약품", "보로노이", "오스코텍", "삼천당제약", "레고켐")),
    ("화장품", ("아모레", "LG생활건강", "코스맥스", "한국콜마", "실리콘투", "브이티", "클리오", "아이패밀리에스씨", "마녀공장", "토니모리", "잉글우드랩", "콜마")),
    ("금융", ("KB금융", "신한지주", "하나금융지주", "우리금융지주", "기업은행", "삼성화재", "삼성생명", "메리츠금융지주", "미래에셋증권", "키움증권", "한국금융지주", "NH투자증권", "카카오뱅크")),
    ("자동차", ("현대차", "기아", "현대모비스", "HL만도", "한온시스템", "성우하이텍", "화신", "에스엘", "서연이화", "명신산업", "현대위아")),
    ("2차전지", ("LG에너지솔루션", "삼성SDI", "에코프로", "에코프로비엠", "포스코퓨처엠", "엘앤에프", "나노신소재", "천보", "대주전자재료", "SK아이이테크놀로지", "피엔티", "윤성에프앤씨")),
    ("인터넷/AI", ("NAVER", "카카오", "더존비즈온", "솔트룩스", "폴라리스AI", "이스트소프트", "마음AI", "플리토", "셀바스AI")),
    ("로봇", ("두산로보틱스", "레인보우로보틱스", "로보티즈", "로보스타", "에스피지", "뉴로메카", "티로보틱스", "유일로보틱스", "브이원텍")),
    ("원전", ("두산에너빌리티", "한전기술", "한전KPS", "우리기술", "우진", "비에이치아이", "보성파워텍", "오르비텍", "일진파워")),
    ("엔터", ("하이브", "JYP", "에스엠", "와이지엔터테인먼트", "디어유", "큐브엔터", "스튜디오드래곤", "CJ ENM")),
    ("게임", ("크래프톤", "넷마블", "엔씨소프트", "펄어비스", "카카오게임즈", "위메이드", "네오위즈", "컴투스", "넥슨게임즈")),
    ("음식료", ("CJ제일제당", "오리온", "농심", "삼양식품", "빙그레", "롯데칠성", "하이트진로", "대상", "풀무원")),
    ("해운", ("HMM", "팬오션", "대한해운", "KSS해운", "흥아해운")),
    ("건설", ("삼성E&A", "현대건설", "대우건설", "GS건설", "DL이앤씨", "HDC현대산업개발", "금호건설", "태영건설")),
    ("철강/소재", ("POSCO홀딩스", "현대제철", "세아베스틸지주", "동국제강", "고려아연", "풍산", "롯데케미칼", "금호석유", "대한유화", "효성티앤씨")),
    ("지주/상사", ("삼성물산", "SK", "LG", "CJ", "GS", "LS", "두산", "포스코인터내셔널", "LX인터내셔널", "현대코퍼레이션")),
]


def _classify_name(name: str) -> str | None:
    for sector, keywords in _SECTOR_RULES:
        if any(keyword in name for keyword in keywords):
            return sector
    return None


def build_candidates(max_rows: int | None = None) -> pd.DataFrame:
    import FinanceDataReader as fdr

    frames = []
    for market in ("KOSPI", "KOSDAQ"):
        df = fdr.StockListing(market)
        if "Code" in df.columns:
            df = df.assign(Code=df["Code"].astype(str).str.zfill(6).str.strip())
        frames.append(_apply_universe_filter(df))

    listing = pd.concat(frames, ignore_index=True)
    listing = listing.sort_values("Marcap", ascending=False, na_position="last")
    if max_rows:
        listing = listing.head(max_rows)

    today = date.today().isoformat()
    rows = []
    for _, row in listing.iterrows():
        name = str(row.get("Name", "")).strip()
        sector = _classify_name(name)
        if not sector:
            continue
        rows.append(
            {
                "ticker": str(row.get("Code", "")).zfill(6),
                "name_kr": name,
                "sector": sector,
                "source": "name-rule",
                "updated_at": today,
            }
        )
    out = pd.DataFrame(rows, columns=["ticker", "name_kr", "sector", "source", "updated_at"])
    if out.empty:
        return out
    return out.drop_duplicates(subset=["ticker"], keep="first").reset_index(drop=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="한국 섹터 매핑 후보 생성")
    parser.add_argument("--max-rows", type=int, default=500, help="시총 상위 N개만 후보 검사")
    parser.add_argument("--apply", action="store_true", help="data/kr_sector_map.csv에 저장")
    parser.add_argument("--preview", type=int, default=80, help="미리보기 출력 행 수")
    args = parser.parse_args()

    candidates = build_candidates(max_rows=args.max_rows)
    if candidates.empty:
        print("섹터 후보가 없습니다.")
        return 1

    print(candidates.head(args.preview).to_string(index=False))
    print(f"\n후보 {len(candidates)}개 / 검사 {args.max_rows}개")

    if args.apply:
        saved = kr_save_sector_map(candidates)
        print(f"저장 완료: data/kr_sector_map.csv ({saved}개)")
    else:
        print("미리보기만 수행했습니다. 저장하려면 --apply를 붙이세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
