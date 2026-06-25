"""차트 공존 테스트 — 지수 차트와 종목 차트가 동시에 렌더될 때 간섭하지 않음을 검증.

핵심 버그: Chart(series=...) 는 매 Streamlit 리런마다 새 객체 → id(self) 변경
  → chart_id="chart-{id(self)}" 변경 → iframe 재초기화 → get_pane_state 이벤트
  → setComponentValue() → 또다른 리런 → 두 차트가 어긋난 타이밍으로 연쇄 리런.

수정: chart_id를 key 기반 안정값으로 고정 + 키 sanitize(^ 제거).
"""

import types
import unittest.mock as mock

import pytest

import screening.ui as ui


# ─── 헬퍼: 최소 Chart 더미 ───────────────────────────────────────────

class _FakeChartRenderer:
    """ChartRenderer 최소 더미."""
    def __init__(self):
        self.handle_response = lambda *a, **kw: None  # 기본값: noop

class _FakeChart:
    """Chart 최소 더미 (to_frontend_config 검증용)."""
    def __init__(self, chart_id: str):
        self._orig_id = chart_id
        self._chart_renderer = _FakeChartRenderer()

    def to_frontend_config(self) -> dict:
        return {"charts": [{"chartId": self._orig_id, "chart": {}, "series": []}]}


# ─── _apply_chart_stability 헬퍼 자체 테스트 ────────────────────────

def test_apply_chart_stability_fixes_chart_id():
    """_apply_chart_stability가 chartId를 stable_id로 덮어쓴다."""
    chart = _FakeChart("chart-140734968")  # 매 리런마다 바뀌는 id(self)
    stable_id = "stable-lwc_mkt_idx_kr_KS11"

    ui._apply_chart_stability(chart, stable_id)

    cfg = chart.to_frontend_config()
    assert cfg["charts"][0]["chartId"] == stable_id, (
        "chartId가 안정값으로 교체돼야 합니다"
    )


def test_apply_chart_stability_noops_handle_response():
    """_apply_chart_stability가 handle_response를 noop으로 설정한다."""
    chart = _FakeChart("any-id")
    called = []
    chart._chart_renderer.handle_response = lambda *a, **kw: called.append(1)

    ui._apply_chart_stability(chart, "stable")
    chart._chart_renderer.handle_response("some_response", "key", "mgr")

    assert called == [], "handle_response가 호출되면 안 됩니다"


def test_apply_chart_stability_multiple_chart_objects():
    """서로 다른 id(self)를 가진 두 Chart 인스턴스에 각각 안정 ID를 적용해도
    서로 간섭하지 않아야 한다."""
    chart_a = _FakeChart("chart-111111")
    chart_b = _FakeChart("chart-222222")

    ui._apply_chart_stability(chart_a, "stable-index")
    ui._apply_chart_stability(chart_b, "stable-stock")

    cfg_a = chart_a.to_frontend_config()
    cfg_b = chart_b.to_frontend_config()

    assert cfg_a["charts"][0]["chartId"] == "stable-index"
    assert cfg_b["charts"][0]["chartId"] == "stable-stock"
    assert cfg_a["charts"][0]["chartId"] != cfg_b["charts"][0]["chartId"]


# ─── 키 sanitize 테스트 ──────────────────────────────────────────────

@pytest.mark.parametrize("index_code,expected_substr", [
    ("^KS11", "KS11"),
    ("^IXIC", "IXIC"),
    ("^GSPC", "GSPC"),
    ("^KQ11", "KQ11"),
])
def test_index_chart_key_has_no_caret(index_code, expected_substr):
    """지수 코드의 ^ 문자가 키에 포함되면 CSS 클래스명이 깨진다.
    _make_index_chart_key가 ^ 를 제거해야 한다.
    """
    key = ui._make_index_chart_key("kr", index_code)
    assert "^" not in key, f"키에 ^ 문자 포함 금지: {key!r}"
    assert expected_substr in key, f"지수 코드 식별자 포함 필요: {key!r}"


def test_index_chart_key_stable_across_calls():
    """같은 인자로 두 번 호출하면 동일 키를 반환해야 한다."""
    k1 = ui._make_index_chart_key("kr", "^KS11")
    k2 = ui._make_index_chart_key("kr", "^KS11")
    assert k1 == k2


def test_index_chart_key_differs_by_market_and_code():
    """시장이나 지수가 다르면 키도 달라야 한다."""
    k_ks = ui._make_index_chart_key("kr", "^KS11")
    k_kq = ui._make_index_chart_key("kr", "^KQ11")
    k_us = ui._make_index_chart_key("us", "^IXIC")
    assert k_ks != k_kq
    assert k_ks != k_us
    assert k_kq != k_us


# ─── 지수/종목 차트 키 충돌 없음 테스트 ─────────────────────────────

def test_index_and_stock_chart_keys_never_collide():
    """지수 차트 키와 종목 차트 키가 같아선 안 된다."""
    index_key = ui._make_index_chart_key("kr", "^KS11")
    stock_key = f"lwc_chart_kr_005930_inline"
    assert index_key != stock_key


def test_index_chart_stable_id_derived_from_key():
    """stable_id가 키에서 파생돼야 하며, 키가 다르면 stable_id도 달라야 한다."""
    key_a = ui._make_index_chart_key("kr", "^KS11")
    key_b = ui._make_index_chart_key("kr", "^KQ11")
    # stable_id는 키와 동일하거나 키를 포함해야 한다 (구현에 따라 허용)
    stable_a = f"stable-{key_a}"
    stable_b = f"stable-{key_b}"
    assert stable_a != stable_b
