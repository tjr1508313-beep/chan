"""주식 스크리닝 웹 앱 (Streamlit 진입점).

미국주식 + 한국주식을 한 화면에 위/아래로 함께 표시한다.

통합 대비 규칙:
    - `st.set_page_config()`는 `main()` 함수 안에서만 호출
    - session_state 키는 모두 `scr_` 접두사 사용
    - CSS는 `screening.theme.apply_theme()`로 주입
    - 캐시 함수는 `us_` / `screen_` 접두사

통합 시 이 파일(`screening.py`)은 폐기되고 `screening/` 패키지만 매매일지 앱에
탭으로 붙일 예정.
"""

import logging

import streamlit as st

from screening.auth import require_password
from screening.cache import init_cache
from screening.cache_sync import sync_from_remote
from screening.theme import apply_theme
from screening.ui import render_screening_page

_LOG = logging.getLogger(__name__)


@st.cache_resource(show_spinner=False)
def _sync_remote_cache_once():
    """앱 프로세스가 살아 있는 동안 1회만 원격 캐시 동기화.

    Streamlit rerun 마다 재호출 방지를 위해 `cache_resource` 사용.
    네트워크 실패는 silent — UI 배지로만 노출.
    """
    result = sync_from_remote(force=False)
    _LOG.info("cache sync: status=%s bytes=%s error=%s",
              result.status, result.bytes_downloaded, result.error)
    return result


@st.cache_resource(show_spinner=False)
def _init_cache_once() -> bool:
    """앱 프로세스 동안 1회만 SQLite 스키마 초기화.

    `CREATE IF NOT EXISTS` 만 있는 idempotent 작업이라 rerun 마다 호출할
    필요가 없다.
    """
    init_cache()
    return True


def main() -> None:
    st.set_page_config(
        page_title="주식 스크리닝",
        page_icon=":chart_with_upwards_trend:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_theme()

    # LS증권 OpenAPI 키: secrets.toml → os.environ (kr_risk 는 streamlit 비의존, env 만 읽음)
    import os
    for _src, _dst in (("ls_app_key", "LS_APP_KEY"), ("ls_app_secret", "LS_APP_SECRET")):
        try:
            if _dst not in os.environ and _src in st.secrets:
                os.environ[_dst] = str(st.secrets[_src])
        except Exception:
            pass  # secrets.toml 없으면 무시 (graceful)

    # 원격 캐시 동기화는 init_cache() 보다 먼저.
    # 받은 DB 가 스키마가 부족해도 init_cache() 가 CREATE IF NOT EXISTS 로 보강.
    _sync_remote_cache_once()

    # 캐시 DB 가 없는 환경(새 체크아웃 등)에서도 읽기 경로가 깨지지 않도록 보장
    _init_cache_once()

    # ─── 비밀번호 잠금 (배포 환경에서만 활성, 로컬은 자동 비활성) ───
    require_password()

    # ─── 본문: 미국주식 + 한국주식 한 화면 ───
    render_screening_page()


if __name__ == "__main__":
    main()
