"""앱 비밀번호 잠금 게이트.

`require_password()` 호출 시 비번 통과 안 하면 입력 폼 표시 후 `st.stop()`.

비번 설정 방법 (둘 중 하나):
    1. `.streamlit/secrets.toml` 에 `app_password = "yourpw"` (배포 환경 권장)
    2. 환경변수 `SCREENING_PASSWORD=yourpw`

비번 미설정이면 자동으로 잠금 비활성화 (로컬 개발 편의).

세션 키: `scr_authenticated` (한 번 통과하면 같은 브라우저 세션 동안 유지).
"""
from __future__ import annotations

import os

import streamlit as st


_KEY_AUTH = "scr_authenticated"


def _get_expected_password() -> str:
    """배포 환경에서 기대하는 비밀번호. 없으면 빈 문자열."""
    pw = ""
    try:
        pw = str(st.secrets.get("app_password", "") or "")
    except (FileNotFoundError, AttributeError, KeyError):
        # secrets.toml 없으면 secrets.get 자체가 FileNotFoundError 던짐
        pw = ""
    if not pw:
        pw = os.environ.get("SCREENING_PASSWORD", "") or ""
    return pw.strip()


def require_password() -> None:
    """비번 통과 안 하면 입력 폼만 띄우고 페이지 렌더링 중단."""
    expected = _get_expected_password()
    if not expected:
        return  # 비번 미설정 → 잠금 비활성화

    if st.session_state.get(_KEY_AUTH):
        return  # 이미 통과

    # ─── 잠금 화면 ───
    st.markdown(
        "<div style='max-width: 360px; margin: 4rem auto;'>"
        "<h2 style='text-align:center;'>🔒 스크리닝</h2>"
        "<p style='text-align:center; color:#6b7280;'>비밀번호를 입력해주세요.</p>"
        "</div>",
        unsafe_allow_html=True,
    )
    cols = st.columns([1, 2, 1])
    with cols[1]:
        pw = st.text_input(
            "비밀번호",
            type="password",
            key="scr_pw_input",
            label_visibility="collapsed",
            placeholder="비밀번호",
        )
        if pw:
            if pw == expected:
                st.session_state[_KEY_AUTH] = True
                st.rerun()
            else:
                st.error("비밀번호가 일치하지 않습니다.")
    st.stop()
