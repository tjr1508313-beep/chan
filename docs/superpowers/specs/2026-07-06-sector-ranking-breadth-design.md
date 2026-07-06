# 섹터 랭킹 개선: 강도×폭 혼합점수 + 극소 섹터 제외

작성일: 2026-07-06

## 배경 / 문제

섹터별 보기에서 **의료정밀(2종목)** 같은 극소 섹터가 강종목 하나(케이씨텍 +67.74%)만으로
전체 1위(+34.62%)에 오르는 현상이 발생. 사용자 의도(지수보다 크게 오르는 추세에 올라타기 +
"섹터 로테이션이 진짜인지" 확인)와 맞지 않음.

현재 정렬은 `sector_score`(섹터 내부 20일수익률 상위 5종목 평균) **단일 기준**이라
종목 수가 적으면 소수 강종목에 휘둘린다.

관련 코드:
- 점수/정렬: `screening/core.py` `screen_build_sector_rankings()` (score 계산 924행, 정렬 947행)
- 극소 섹터 컷: 같은 함수 `min_sector_size` (910행), 굽는 기본값 `screening/sector.py:409`(현재 2)
- 표시: `screening/ui.py` 는 전부 저장된 `rank` 순서를 그대로 읽음
  (타일 `_build_sector_tiles_css`, 최강섹터 카드 `_build_sector_metrics_html` `iloc[0]`,
   상위 12개 `summary.head(12)` @2185행)

## 목표

"넓게 강한 섹터"가 상위에 오도록 정렬 기준을 바꾸되, 극소 섹터는 랭킹에서 제외한다.

## 설계

### 1. 극소 섹터 제외: `min_sector_size` 2 → 3

통과 종목이 **3개 미만**인 섹터는 요약/타일/랭킹에서 제외. (의료정밀 2종목 → 사라짐)

변경 지점 (섹터 스냅샷을 굽는 경로 + 폴백):
- `screening/sector.py:409` `screen_rebuild_sector_snapshot(min_sector_size=2)` → `3`
- `screening/sector.py:271`, `:317` 각 빌더 기본값 `1` → `3`
- `screening/core.py:821` `screen_build_sector_rankings(min_sector_size=1)` → `3`
- `screening/ui.py:177`, `:202` "지금 계산" 폴백 기본값 `1` → `3`

### 2. 정렬 기준을 강도×폭 혼합점수로

`screen_build_sector_rankings()`의 summary 정렬(현재 947~951행)을 바꾼다.

**혼합점수(정렬 전용, 비저장):**
```
sector_rank_score = sector_score × positive_ratio
```
- **강도 `sector_score`** = 섹터 내부 20일수익률 **상위 5종목** 평균 (기존 유지, 살 만한 주도주의 힘)
- **폭 `positive_ratio`** = 섹터 **전체 종목** 중 20일수익률 양수 비율 (진짜 섹터 로테이션인지)
- 상위5(강도)와 전체(폭)로 보는 범위가 달라 **서로 다른 정보** → 중복 없이 결합.
  강도까지 전체 평균으로 잡으면 폭과 이중계산되어 폭에 과도 편향되므로 상위 5종목 유지.

**정렬:** `[sector_rank_score, sector_score, positive_ratio, stock_count]` 전부 내림차순.
(1차 혼합점수. 나머지는 동점·음수 꼬리 처리용 보조 키.)

`sector_rank_score`는 계산용 임시 컬럼으로만 쓰고 반환 시 `_SECTOR_SUMMARY_COLUMNS`만 선택해
자연 탈락 → **DB 스키마/저장 포맷 변경 없음.** 정렬 결과가 `rank`(1..N)로 굳어 저장되고
UI는 저장 순서를 그대로 읽으므로 화면 코드 변경 불필요.

### 3. 타일 표시 숫자는 그대로 강도(%)

정렬만 혼합점수로 바뀌고, 타일/카드에 뜨는 값은 기존 `sector_score`(원래 강도 %) 유지.
사용자가 읽는 숫자는 "섹터가 얼마 올랐나"라 직관적, 순서만 폭을 반영.
결과적으로 +20% 타일이 +34% 타일 위에 올 수 있음(넓게 강한 섹터가 위) — 의도된 동작.

## 영향 / 재계산

- 무거운 계산은 새로고침 때 `sector_snapshot`에 구워지므로, **코드 반영 후 새로고침(리빌드)** 해야
  실제 화면에 반영됨. (KR: 코스피+코스닥 합산, US: ^IXIC/^GSPC 각각)
- `상승 섹터 N/M` 카운트는 `sector_score>0` 기준 그대로 → 영향 없음.

## 테스트 (`tests/test_core_sector.py`)

- 기존 `test_..._scores_leadership_by_top_returns`: 두 섹터 모두 양수비율 1.0이라 순서 불변 → 통과 유지.
- 신규: **폭이 순위를 뒤집는** 케이스
  - A섹터: 상위5 강도 높음 + 양수비율 낮음(절반만 상승)
  - B섹터: 강도 약간 낮지만 양수비율 1.0
  - → `sector_rank_score` 기준 B가 A보다 위로 오는지 검증.
- 신규/수정: `min_sector_size=3` 기본으로 3종목 미만 섹터가 제외되는지.

## 문서 갱신

`CLAUDE.md` 섹터 분석 섹션:
- "섹터 정렬 = sector_score …" → "정렬 = 강도(상위5 평균) × 양수비율 혼합, 표시는 강도(%)"
- "min_sector_size=1이라 1종목 섹터도" 관련 서술 → "3종목 미만 제외"로 갱신.
