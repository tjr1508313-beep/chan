# 섹터 랭킹 개선(지수 대비 강도×폭 혼합) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 섹터 랭킹을 "지수 대비(rs) 강도×폭"의 순위-백분위 혼합점수로 바꾸고, 극소 섹터(3종목 미만)를 제외하며, KR 섹터는 코스피(KS11) 단독으로 계산한다.

**Architecture:** 무거운 섹터 계산은 새로고침 때 `sector_snapshot`에 굽고 화면은 읽기만 한다. 점수/정렬은 `screening/core.py`의 `screen_build_sector_rankings()` 한 함수에 집중돼 있고, UI는 저장된 `rank` 순서를 그대로 읽으므로 정렬 로직만 바꾸면 화면 전체가 따라온다. KR을 코스피 단독으로 굽는 변경은 `screening/sector.py`의 `screen_rebuild_sector_snapshot()` KR 분기 한 곳.

**Tech Stack:** Python, pandas, pytest, Streamlit(변경 없음).

## Global Constraints

- `rs = 종목수익률 − 지수수익률` (`_relative_strength`, [screening/core.py:543](../../../screening/core.py)) — 이미 계산된 `rs` 컬럼을 그대로 사용. 별도 벤치마크 인자 없음.
- 혼합 가중치: **강도 0.7 / 폭 0.3** (강도 우선).
- 극소 섹터 제외 하한: **3종목** (`min_sector_size=3`).
- KR 섹터 모집단: **코스피(KS11) 단독**, 코스닥(KQ11) 제외. US는 ^IXIC/^GSPC 각각(변경 없음).
- DB 스키마/저장 포맷 **변경 금지**: `sector_rank_score`/`beat_ratio`는 계산용 임시 컬럼이며 반환 시 `_SECTOR_SUMMARY_COLUMNS`만 선택해 자연 탈락.
- 테스트는 TDD(실패 테스트 → 최소 구현 → 통과). 작업마다 커밋.
- 실행 명령은 `py -m pytest ...` (프로젝트 Windows 환경).

---

### Task 1: `screen_build_sector_rankings` — rs 기반 강도/폭 + 백분위 혼합 정렬 + 하한 3

**Files:**
- Modify: `screening/core.py` (상수 추가 `_SECTOR_SUMMARY_COLUMNS` 근처 ~662행; 함수 `screen_build_sector_rankings` 816~964행)
- Test: `tests/test_core_sector.py`

**Interfaces:**
- Consumes: `ranked`(컬럼 `ticker`,`return_n`,`rs` 필수), `metadata`(옵션). 시그니처 유지:
  `screen_build_sector_rankings(ranked, metadata=None, *, top_n_per_sector=5, min_sector_size=3, unknown_sector="미분류") -> (summary_df, members_df)`.
- Produces: `summary_df`는 기존 `_SECTOR_SUMMARY_COLUMNS`(변경 없음). `sector_score`의 **의미가 raw 수익률 → rs(지수 대비) 상위 5종목 평균**으로 바뀜. `rank`는 백분위 혼합점수 내림차순.

- [ ] **Step 1: 기존 테스트를 새 정의에 맞게 수정 (실패 상태로)**

`tests/test_core_sector.py`에서 아래 3개 테스트를 교체한다.

```python
def test_screen_build_sector_rankings_scores_leadership_by_top_rs():
    ranked = pd.DataFrame(
        [
            {"ticker": "AAA", "return_n": 0.30, "rs": 0.20, "rs_weighted": 1.5},
            {"ticker": "BBB", "return_n": 0.20, "rs": 0.10, "rs_weighted": 1.4},
            {"ticker": "CCC", "return_n": 0.12, "rs": 0.02, "rs_weighted": 1.1},
            {"ticker": "DDD", "return_n": 0.04, "rs": -0.06, "rs_weighted": 0.9},
        ]
    )
    meta = pd.DataFrame(
        [
            {"ticker": "AAA", "sector": "Tech", "name_kr": "에이"},
            {"ticker": "BBB", "sector": "Tech", "name_kr": "비"},
            {"ticker": "CCC", "sector": "Energy", "name_kr": "씨"},
            {"ticker": "DDD", "sector": "Energy", "name_kr": "디"},
        ]
    )

    summary, members = core.screen_build_sector_rankings(
        ranked, meta, top_n_per_sector=2, min_sector_size=1
    )

    assert list(summary["sector"]) == ["Tech", "Energy"]
    # 강도 = 상위 2종목 rs 평균 (0.20, 0.10) → 0.15
    assert summary.loc[0, "sector_score"] == pytest.approx(0.15)
    assert summary.loc[0, "top_ticker"] == "AAA"
    assert summary.loc[0, "top_name"] == "에이"
    assert list(members[members["sector"] == "Tech"]["ticker"]) == ["AAA", "BBB"]
    assert list(members[members["sector"] == "Tech"]["rank_in_sector"]) == [1, 2]


def test_screen_build_sector_rankings_handles_missing_sector_as_unknown():
    ranked = pd.DataFrame(
        [
            {"ticker": "AAA", "return_n": 0.10, "rs": 0.05},
            {"ticker": "BBB", "return_n": 0.03, "rs": -0.02},
        ]
    )
    meta = pd.DataFrame(
        [
            {"ticker": "AAA", "sector": ""},
            {"ticker": "BBB", "sector": None},
        ]
    )

    summary, members = core.screen_build_sector_rankings(
        ranked, meta, min_sector_size=1
    )

    assert list(summary["sector"]) == ["미분류"]
    assert summary.loc[0, "stock_count"] == 2
    assert set(members["sector"]) == {"미분류"}


def test_screen_build_sector_rankings_can_filter_tiny_sectors():
    ranked = pd.DataFrame(
        [
            {"ticker": "AAA", "return_n": 0.30, "rs": 0.20},
            {"ticker": "BBB", "return_n": 0.20, "rs": 0.10},
            {"ticker": "CCC", "return_n": 0.50, "rs": 0.40},
        ]
    )
    meta = pd.DataFrame(
        [
            {"ticker": "AAA", "sector": "Tech"},
            {"ticker": "BBB", "sector": "Tech"},
            {"ticker": "CCC", "sector": "Solo"},
        ]
    )

    summary, members = core.screen_build_sector_rankings(
        ranked, meta, min_sector_size=2
    )

    assert list(summary["sector"]) == ["Tech"]
    assert set(members["sector"]) == {"Tech"}
```

파일 상단 import에 `pytest`가 없으면 추가한다:
```python
import pytest
```

- [ ] **Step 2: 새 동작 테스트 추가 (실패 상태)**

`tests/test_core_sector.py` 끝에 추가한다.

```python
def test_sector_rankings_breadth_breaks_tie_on_equal_strength():
    # 두 섹터 강도(상위N rs 평균) 동일(0.05), 폭(rs>0 비율)만 다름 → 폭 큰 쪽이 위
    ranked = pd.DataFrame(
        [
            {"ticker": "A1", "return_n": 0.06, "rs": 0.06},
            {"ticker": "A2", "return_n": 0.04, "rs": 0.04},
            {"ticker": "A3", "return_n": 0.05, "rs": 0.05},   # Broad: rs 평균 0.05, 폭 3/3=1.0
            {"ticker": "B1", "return_n": 0.10, "rs": 0.10},
            {"ticker": "B2", "return_n": 0.10, "rs": 0.10},
            {"ticker": "B3", "return_n": -0.05, "rs": -0.05},  # Narrow: rs 평균 0.05, 폭 2/3
        ]
    )
    meta = pd.DataFrame(
        [
            {"ticker": "A1", "sector": "Broad"},
            {"ticker": "A2", "sector": "Broad"},
            {"ticker": "A3", "sector": "Broad"},
            {"ticker": "B1", "sector": "Narrow"},
            {"ticker": "B2", "sector": "Narrow"},
            {"ticker": "B3", "sector": "Narrow"},
        ]
    )

    summary, _ = core.screen_build_sector_rankings(ranked, meta, min_sector_size=3)

    assert summary.loc[0, "sector_score"] == pytest.approx(0.05)
    assert summary.loc[1, "sector_score"] == pytest.approx(0.05)
    assert list(summary["sector"]) == ["Broad", "Narrow"]


def test_sector_rankings_bear_market_puts_least_negative_on_top():
    # 전 섹터 하락(rs<0): 곱셈이라면 뒤집혔을 배치. 백분위 혼합은 덜 빠진 섹터를 위로.
    ranked = pd.DataFrame(
        [
            {"ticker": "X1", "return_n": -0.02, "rs": -0.02},
            {"ticker": "X2", "return_n": -0.03, "rs": -0.03},
            {"ticker": "X3", "return_n": -0.04, "rs": -0.04},  # Mild: rs 평균 -0.03
            {"ticker": "Y1", "return_n": -0.06, "rs": -0.06},
            {"ticker": "Y2", "return_n": -0.07, "rs": -0.07},
            {"ticker": "Y3", "return_n": -0.08, "rs": -0.08},  # Deep: rs 평균 -0.07
        ]
    )
    meta = pd.DataFrame(
        [
            {"ticker": "X1", "sector": "Mild"},
            {"ticker": "X2", "sector": "Mild"},
            {"ticker": "X3", "sector": "Mild"},
            {"ticker": "Y1", "sector": "Deep"},
            {"ticker": "Y2", "sector": "Deep"},
            {"ticker": "Y3", "sector": "Deep"},
        ]
    )

    summary, _ = core.screen_build_sector_rankings(ranked, meta, min_sector_size=3)

    assert list(summary["sector"]) == ["Mild", "Deep"]


def test_sector_rankings_default_min_size_excludes_two_stock_sector():
    ranked = pd.DataFrame(
        [
            {"ticker": "T1", "return_n": 0.10, "rs": 0.05},
            {"ticker": "T2", "return_n": 0.08, "rs": 0.03},
            {"ticker": "T3", "return_n": 0.06, "rs": 0.01},
            {"ticker": "P1", "return_n": 0.20, "rs": 0.15},
            {"ticker": "P2", "return_n": 0.18, "rs": 0.13},
        ]
    )
    meta = pd.DataFrame(
        [
            {"ticker": "T1", "sector": "Three"},
            {"ticker": "T2", "sector": "Three"},
            {"ticker": "T3", "sector": "Three"},
            {"ticker": "P1", "sector": "Two"},
            {"ticker": "P2", "sector": "Two"},
        ]
    )

    # min_sector_size 미지정 → 기본 3 → 2종목 섹터 제외
    summary, members = core.screen_build_sector_rankings(ranked, meta)

    assert list(summary["sector"]) == ["Three"]
    assert set(members["sector"]) == {"Three"}
```

- [ ] **Step 3: 테스트 실행 → 실패 확인**

Run: `py -m pytest tests/test_core_sector.py -v`
Expected: 위 5개 테스트 FAIL (기존 정의가 raw 수익률 기반·기본 하한 1이라 값/순서 불일치, 신규 테스트는 기본 하한 1이라 2종목 섹터 미제외).

- [ ] **Step 4: 상수 추가**

`screening/core.py`의 `_SECTOR_SUMMARY_COLUMNS = [` (662행) 바로 위에 추가:

```python
# 섹터 정렬 혼합점수 = 강도 백분위 × w + 폭 백분위 × (1-w). 강도 우선.
_SECTOR_STRENGTH_WEIGHT = 0.7
```

- [ ] **Step 5: 함수 기본값·집계·정렬 구현**

(a) 시그니처 기본값 변경 — `screening/core.py:821`:

```python
    min_sector_size: int = 3,
```

(b) 멤버 정렬 키를 `return_n` → `rs` 로 (현재 903~906행):

```python
    members = members.sort_values(
        ["sector", "rs"], ascending=[True, False], kind="mergesort"
    ).copy()
    members["rank_in_sector"] = members.groupby("sector").cumcount() + 1
```

(c) 섹터별 집계 루프에서 leaders/top/score를 rs 기준으로, breadth(`beat_ratio`) 추가 (현재 912~924행):

```python
        ordered = group.sort_values("rs", ascending=False, kind="mergesort")
        leaders = ordered.head(max(int(top_n_per_sector), 1))
        top = ordered.iloc[0]
        summary_rows.append(
            {
                "sector": sector,
                "stock_count": int(len(group)),
                "positive_count": int((group["return_n"] > 0).sum()),
                "positive_ratio": float((group["return_n"] > 0).mean()),
                "avg_return_n": float(group["return_n"].mean()),
                "median_return_n": float(group["return_n"].median()),
                "top_return_n": float(top["return_n"]),
                "sector_score": float(leaders["rs"].mean()),
                "beat_ratio": float((group["rs"] > 0).mean()),
                "avg_rs": float(group["rs"].mean()),
```

(위 블록은 `"sector_score"` 줄을 `leaders["return_n"]`→`leaders["rs"]`로 바꾸고 그 아래 `"beat_ratio"` 한 줄을 추가하는 것. `median_rs` 이하 나머지 딕셔너리 항목은 그대로 유지.)

(d) 정렬을 백분위 혼합점수로 (현재 946~951행):

```python
    summary = pd.DataFrame(summary_rows)
    strength_pct = summary["sector_score"].rank(pct=True, method="average")
    breadth_pct = summary["beat_ratio"].rank(pct=True, method="average")
    summary["sector_rank_score"] = (
        _SECTOR_STRENGTH_WEIGHT * strength_pct
        + (1.0 - _SECTOR_STRENGTH_WEIGHT) * breadth_pct
    )
    summary = summary.sort_values(
        ["sector_rank_score", "sector_score", "beat_ratio", "stock_count"],
        ascending=[False, False, False, False],
        kind="mergesort",
    ).reset_index(drop=True)
    summary.insert(0, "rank", range(1, len(summary) + 1))
```

(반환부 964행 `return summary[_SECTOR_SUMMARY_COLUMNS], members[_SECTOR_MEMBER_COLUMNS]`는 그대로 — 임시 컬럼 `sector_rank_score`/`beat_ratio` 자동 탈락.)

- [ ] **Step 6: 테스트 실행 → 통과 확인**

Run: `py -m pytest tests/test_core_sector.py -v`
Expected: PASS (전체).

- [ ] **Step 7: 커밋**

```bash
git add screening/core.py tests/test_core_sector.py
git commit -m "섹터 점수 rs(지수대비) 기반 강도·폭 백분위 혼합 정렬 + 하한 3"
```

---

### Task 2: `min_sector_size` 기본값 3으로 전파 (빌더/폴백)

**Files:**
- Modify: `screening/sector.py` (`screen_build_sector_snapshot` 271행, `screen_build_combined_sector_snapshot` 317행, `screen_rebuild_sector_snapshot` 409행)
- Modify: `screening/ui.py` (`ui_load_sector_snapshot` 177행, `ui_load_combined_sector_snapshot` 202행)

**Interfaces:**
- Consumes: Task 1의 `screen_build_sector_rankings(min_sector_size=3)`.
- Produces: 굽기/폴백 경로가 기본 3으로 하한을 넘김.

- [ ] **Step 1: sector.py 기본값 3으로**

`screening/sector.py`에서 세 곳의 `min_sector_size` 기본값을 3으로 변경:
- 271행 `min_sector_size=1` → `min_sector_size=3`
- 317행 `min_sector_size=1` → `min_sector_size=3`
- 409행 `min_sector_size=2` → `min_sector_size=3`

- [ ] **Step 2: ui.py 폴백 기본값 3으로**

`screening/ui.py`:
- 177행 `min_sector_size: int = 1,` → `min_sector_size: int = 3,`
- 202행 `min_sector_size: int = 1,` → `min_sector_size: int = 3,`

- [ ] **Step 3: 관련 테스트 회귀 확인**

Run: `py -m pytest tests/test_core_sector.py tests/test_sector_snapshot.py tests/test_show_sector_rs.py -v`
Expected: PASS (신규 하한이 기존 테스트 fixture를 깨지 않는지 확인. 깨지면 해당 테스트에 `min_sector_size` 명시값을 넘겨 의도를 고정).

- [ ] **Step 4: 커밋**

```bash
git add screening/sector.py screening/ui.py
git commit -m "섹터 극소필터 기본 하한 3으로 전파(빌더/폴백)"
```

---

### Task 3: KR 섹터 스냅샷을 코스피(KS11) 단독으로 굽기

**Files:**
- Modify: `screening/sector.py` `screen_rebuild_sector_snapshot()` KR 분기 (416~431행)
- Test: `tests/test_sector_snapshot.py`

**Interfaces:**
- Consumes: 기존 `screen_build_sector_snapshot("KS11", ...)`, `cache_load_universe("KS11")`, `_KR_SECTOR_SCOPE`, `_KR_SECTOR_FILTER`.
- Produces: scope `"KR"`에 **KS11 단독** 스냅샷 저장. 코스닥(KQ11)은 호출하지 않음. `screen_build_combined_sector_snapshot`은 코드에 남기되 이 경로에서 미사용.

- [ ] **Step 1: 실패 테스트 추가**

`tests/test_sector_snapshot.py` 끝에 추가한다. (단일 빌더가 KS11로 호출되고, combined/KQ11이 호출되지 않음을 검증.)

```python
def test_rebuild_kr_uses_kospi_only(monkeypatch):
    single_calls = []
    combined_calls = []

    def fake_single(index_code, **kwargs):
        single_calls.append((index_code, kwargs))
        return {
            "sector_summary": pd.DataFrame([{"sector": "반도체"}]),
            "sector_members": pd.DataFrame([{"sector": "반도체", "ticker": "005930"}]),
        }

    def fake_combined(index_codes, **kwargs):
        combined_calls.append((index_codes, kwargs))
        return {"sector_summary": pd.DataFrame(), "sector_members": pd.DataFrame()}

    saved = {}

    def fake_save(scope, period, summary_df, members_df):
        saved["scope"] = scope
        return True

    monkeypatch.setattr(sector, "screen_build_sector_snapshot", fake_single, raising=False)
    monkeypatch.setattr(
        sector, "screen_build_combined_sector_snapshot", fake_combined, raising=False
    )
    monkeypatch.setattr(sector, "cache_save_sector_snapshot", fake_save, raising=False)
    monkeypatch.setattr(
        sector, "cache_load_universe", lambda code: ["005930"], raising=False
    )

    result = sector.screen_rebuild_sector_snapshot("kr")

    assert combined_calls == []
    assert len(single_calls) == 1
    assert single_calls[0][0] == "KS11"
    assert saved["scope"] == sector._KR_SECTOR_SCOPE
    assert result[sector._KR_SECTOR_SCOPE] == 1
```

`tests/test_sector_snapshot.py` 상단 import에 `pandas as pd`, `screening.sector as sector`가 이미 있는지 확인하고 없으면 추가.

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `py -m pytest tests/test_sector_snapshot.py::test_rebuild_kr_uses_kospi_only -v`
Expected: FAIL (현재 KR 분기가 `screen_build_combined_sector_snapshot`를 호출 → `combined_calls != []`).

- [ ] **Step 3: KR 분기를 KS11 단독으로 구현**

`screening/sector.py` `screen_rebuild_sector_snapshot()`의 KR 분기(416~431행)를 아래로 교체:

```python
    saved: dict[str, int] = {}
    if str(market).lower() == "kr":
        # 코스피(KS11) 단독으로 섹터 계산. 코스닥은 이번엔 제외(추후 별도).
        ks = cache_load_universe("KS11") or []
        snap = screen_build_sector_snapshot(
            "KS11",
            period=period,
            top_n_per_sector=5,
            min_sector_size=min_sector_size,
            tickers=ks,
            filter_config=dict(_KR_SECTOR_FILTER),
        )
        cache_save_sector_snapshot(
            _KR_SECTOR_SCOPE, period, snap["sector_summary"], snap["sector_members"]
        )
        saved[_KR_SECTOR_SCOPE] = int(len(snap["sector_summary"]))
```

(US `else` 분기는 그대로 둔다.)

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `py -m pytest tests/test_sector_snapshot.py -v`
Expected: PASS (신규 + 기존).

- [ ] **Step 5: 커밋**

```bash
git add screening/sector.py tests/test_sector_snapshot.py
git commit -m "KR 섹터 스냅샷 코스피(KS11) 단독 계산으로 전환(코스닥 제외)"
```

---

### Task 4: UI 라벨 문구를 "지수 대비" 기준으로 정리

**Files:**
- Modify: `screening/ui.py` (943행, 2004행, 2160행)

**Interfaces:**
- Consumes: Task 1 이후 `sector_score`가 rs(지수 대비) 값. 순수 표시 문구만 변경 — 로직/데이터 변화 없음.
- Produces: 화면 문구가 정렬 의미(지수 대비 강도)와 일치.

- [ ] **Step 1: "상승 섹터" → "지수 이긴 섹터"**

`screening/ui.py` 2004행:
```python
        "<div class='scr-sec-metric'><div class='lb'>지수 이긴 섹터</div>"
```

- [ ] **Step 2: 전체 섹터 토글 help 문구**

`screening/ui.py` 943행:
```python
            help="기본은 지수 대비 강도 상위 12개 섹터만 표시(저장은 전체).",
```

- [ ] **Step 3: `_render_sector_view` docstring 문구**

`screening/ui.py` 2160행:
```python
    지수 대비 강도 상위 12개 섹터만 노출(나머지는 저장만). 타일 클릭 → 저장된 종목 즉시 펼침.
```

- [ ] **Step 4: import/구문 회귀 확인**

Run: `py -c "import screening.ui"`
Expected: 에러 없이 종료(문법/임포트 정상).

- [ ] **Step 5: 커밋**

```bash
git add screening/ui.py
git commit -m "섹터 화면 문구를 지수 대비 기준으로 정리"
```

---

### Task 5: CLAUDE.md 섹터 문서 갱신

**Files:**
- Modify: `CLAUDE.md` (섹터 분석 방향 섹션)

**Interfaces:**
- Consumes: Task 1~4의 확정 동작.
- Produces: 문서가 실제 동작과 일치.

- [ ] **Step 1: 백엔드 기준 서술 교체**

`CLAUDE.md`에서 다음 줄을 교체:
- `- 백엔드 기준: sector_score = 섹터 내부 상위 N개 종목 return_n 평균`
  →
  `- 백엔드 기준: 강도 = 섹터 내부 rs(지수 대비) 상위 5종목 평균 / 폭 = rs>0(지수 이긴) 비율`
  `- 섹터 정렬 = 0.7×강도_백분위 + 0.3×폭_백분위 (순위-백분위라 하락장에서도 순위 유지). 표시 숫자 = 지수 대비 강도(%p)`
  `- 3종목 미만 섹터는 제외(min_sector_size=3)`

- [ ] **Step 2: 한국 합산 서술 교체**

`- **한국은 코스피+코스닥 합산**: ...` 로 시작하는 항목을 다음으로 교체:
- `- **한국 섹터는 코스피(KS11) 단독 계산**: 코스닥(KQ11)은 이번엔 제외(추후 별도 화면 + 합산 재논의). 벤치마크가 KS11 하나라 KQ11 이상치 왜곡 없음. rs가 곧 KS11 대비 초과수익.`

(`screen_build_combined_sector_snapshot`는 코드에 남아 있으나 현재 KR 굽기 경로에서 미사용임을 한 줄 덧붙인다.)

- [ ] **Step 3: sector_score 의미 주석 갱신**

precompute 문단의 `계산 기준 고정(RS 20일, 거래대금 느슨 필터)` 부근에서 sector_score를 "raw 수익률"로 설명한 잔재가 있으면 "rs(지수 대비) 상위5 평균, 정렬은 백분위 혼합"으로 정정한다.

- [ ] **Step 4: 커밋**

```bash
git add CLAUDE.md
git commit -m "문서: 섹터 랭킹 rs 기반 혼합점수·코스피 단독 계산 반영"
```

---

## 실행 후 수동 확인 (전체 완료 뒤 1회)

- [ ] 로컬 앱 새로고침(또는 `py scripts/refresh_cache.py`)으로 `sector_snapshot` 리빌드 → 화면에서
  KR 섹터가 코스피 종목만으로 뜨고, 3종목 미만 섹터가 사라졌는지, 타일 숫자가 지수 대비(%p)인지 확인.
- [ ] `py -m pytest tests/ -q` 전체 회귀.
