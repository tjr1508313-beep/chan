# 섹터 랭킹 개선: 지수 대비(RS) 강도×폭 혼합점수 + 극소 섹터 제외

작성일: 2026-07-06

## 배경 / 문제

섹터별 보기에서 **의료정밀(2종목)** 같은 극소 섹터가 강종목 하나(케이씨텍 +67.74%)만으로
전체 1위(+34.62%)에 오르는 현상이 발생. 사용자 의도(**지수보다 크게 오르는 추세에 올라타기** +
"섹터 로테이션이 진짜인지" 확인)와 맞지 않음.

두 가지 결함:
1. 현재 정렬은 `sector_score`(섹터 내부 20일 raw수익률 상위 5종목 평균) **단일 기준**이라
   종목 수가 적으면 소수 강종목에 휘둘림.
2. 강도·폭 모두 **raw 수익률(0 기준)** 이라, 코스피가 박살나면 전 섹터가 음수·양수비율≈0 →
   "코스피보다 덜 빠진 섹터"를 못 봄. 게다가 `강도(음수) × 폭` 곱셈은 하락장에서 **순위가 뒤집힘**
   (폭이 더 나쁜 섹터가 위로 옴).

## 목표

"**지수 대비** 넓게 강한 섹터"가 상위에 오도록 정렬을 바꾸고, 상승장·하락장 모두에서 순위가
일관되게 유지되도록 한다. 극소 섹터는 제외.

## 핵심 결정 (확정)

- **KR 섹터는 코스피(KS11)만으로 계산** — 코스닥(KQ11)은 이번엔 **제외**. (코스닥은 추후 별도,
  둘의 합산은 다음 계획에서 재논의.) → 벤치마크가 KS11 하나로 고정되어 KQ11 이상치 함정 제거.
  US는 기존대로 ^IXIC / ^GSPC 각각.
- **강도·폭 모두 "지수 대비"(rs = 종목수익률 − 지수수익률)로 측정.** `rs`는 이미
  `_relative_strength = stock_return − index_return`([core.py:547](../../../screening/core.py))으로
  계산돼 있어 별도 벤치마크 인자 없이 기존 `rs` 컬럼을 그대로 사용.
- **결합은 순위-백분위 가중합(부호 안전), w=0.7.**
- **타일/카드 표시 숫자 = 지수 대비 강도(%p).**
- **min_sector_size = 3** (3종목 미만 제외).

## 설계

### 1. KR 스냅샷을 KS11 단일 지수로 굽기

`screening/sector.py` `screen_rebuild_sector_snapshot("kr")`:
- 현재: `screen_build_combined_sector_snapshot(["KS11","KQ11"], ...)`
- 변경: `screen_build_sector_snapshot("KS11", ...)` 로 **KS11만** 계산해 기존 scope `"KR"`(`_KR_SECTOR_SCOPE`)에 저장.
- `screen_build_combined_sector_snapshot`은 삭제하지 않고 남겨둠(추후 코스닥 합산 재논의용). 이번엔 호출만 안 함.
- US 경로(`^IXIC`/`^GSPC` 각각)는 변경 없음.

### 2. 강도·폭을 rs 기반으로 재정의

`screening/core.py` `screen_build_sector_rankings()` 섹터별 집계부(현재 909~938행):

- **강도 `sector_score`** = 섹터 내부 rs **상위 5종목의 `rs` 평균** (지수 대비 초과수익).
  - ⚠️ 정렬 기준을 rs로 바꾸므로 상위 5 선정도 `return_n` 대신 **`rs` 내림차순**으로 뽑는다
    (leaders/rank_in_sector 정렬 키를 `rs`로 통일).
  - `top_return_n`, `avg_return_n`, `median_return_n` 등 raw 지표는 **참고용으로 유지**.
- **폭(breadth)** = 섹터 전체 중 **`rs > 0`(지수를 이긴)** 종목 비율. 정렬용 임시값(`beat_ratio`).
  - 기존 `positive_ratio`(raw 수익률>0 비율)는 컬럼으로 **유지**(상세 헤더 "양수 N%" 표시용).

### 3. 순위-백분위 혼합점수로 정렬 (부호 안전)

summary_rows 생성 후, 섹터들끼리:
```
강도_pct = rank_pct(sector_score)        # 0~1, 값이 클수록 1에 가까움
폭_pct   = rank_pct(beat_ratio)          # 0~1
sector_rank_score = 0.7 * 강도_pct + 0.3 * 폭_pct
```
- 백분위(순위 기반)라 강도가 음수든 양수든 **항상 단조** → 하락장에서도 "덜 빠진/지수 이긴 섹터"가
  자연스럽게 위로. 곱셈의 부호 뒤집힘 문제 없음.
- `rank_pct`는 `Series.rank(pct=True)` 사용(동점 평균순위).
- **정렬:** `[sector_rank_score, sector_score, beat_ratio, stock_count]` 내림차순.
- `sector_rank_score`/`beat_ratio`는 계산용 임시 컬럼 → 반환 시 `_SECTOR_SUMMARY_COLUMNS`만
  선택하므로 자연 탈락. **DB 스키마/저장 포맷 변경 없음.** 정렬 결과가 `rank`(1..N)로 저장되고
  UI는 저장 순서를 그대로 읽으므로 화면 정렬 코드 변경 불필요.

### 4. 극소 섹터 제외: `min_sector_size` → 3

- `screening/sector.py`: `screen_rebuild_sector_snapshot(min_sector_size=2→3)`,
  각 빌더 기본값 `screen_build_sector_snapshot`/`screen_build_combined_sector_snapshot`(현 `1`) → `3`.
- `screening/core.py:821` `screen_build_sector_rankings(min_sector_size=1→3)`.
- `screening/ui.py` "지금 계산" 폴백 기본값(현 `1`) → `3`.

### 5. 표시: 지수 대비 강도(%p)

- `sector_score`가 이제 rs 기반이므로 타일·최강섹터 카드가 자동으로 **지수 대비 강도**를 표시.
  숫자 포맷(`_sector_pct`)·색(`_sector_tint`, >0 빨강=지수 이김)은 그대로 재사용.
- **라벨/설명 문구 갱신**(`screening/ui.py`, `theme.py` 등): "수익률"·"양수 섹터" 뉘앙스를
  "지수 대비"·"지수 이긴 섹터"로 다듬음. (기능 아닌 텍스트 정리 — 과하지 않게.)
- `상승 섹터 N/M`(`sector_score>0`) = 이제 "지수를 이긴 섹터 수" 의미로 자연 전환.

## 영향 / 재계산

- 무거운 계산은 새로고침 때 `sector_snapshot`에 구워지므로 **코드 반영 후 새로고침(리빌드)** 필요.
  (KR: KS11 단독, US: ^IXIC/^GSPC 각각.)
- KR 섹터에서 코스닥 종목이 빠지므로 섹터별 종목 수·구성이 달라짐(의도됨).

## 테스트 (`tests/test_core_sector.py`)

- **수정** `test_..._scores_leadership_by_top_returns`: `sector_score` 기대값을 raw→**rs 기반**으로 갱신
  (예: Tech 상위2 rs 평균). 정렬은 백분위 혼합 기준으로 재검증.
- **수정** `test_..._handles_missing_sector_as_unknown`: 2종목 fixture라 기본 `min_sector_size=3`이면
  빈 결과 → `min_sector_size=1` 명시 또는 3종목으로 보강.
- **신규** 하락장 부호 케이스: 모든 섹터 강도 음수일 때, "덜 빠진(rs 덜 음수)+폭 넓은" 섹터가
  1위로 오는지(곱셈이면 뒤집혔을 배치) 검증.
- **신규** 폭이 순위를 가르는 케이스: 강도 비슷·폭 차이 → 폭 높은 섹터가 위.
- **신규/수정**: `min_sector_size=3` 기본으로 3종목 미만 섹터 제외 확인.

## 문서 갱신 (`CLAUDE.md` 섹터 분석 섹션)

- "한국은 코스피+코스닥 합산" → **"KR 섹터는 KS11(코스피) 단독 계산, 코스닥 제외(추후 별도)"**.
- "sector_score = 섹터 내부 상위 N개 종목 return_n 평균" →
  **"강도 = 상위 5종목 rs(지수 대비) 평균, 정렬 = 0.7×강도_백분위 + 0.3×폭(rs>0 비율)_백분위,
  표시는 지수 대비 강도(%p)"**.
- "min_sector_size" 관련 서술 → "3종목 미만 제외"로 갱신.
