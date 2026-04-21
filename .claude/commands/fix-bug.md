버그를 분석하고 수정한다. 사용자가 버그를 설명하면 아래 순서로 진행해줘.

1. **원인 파악**: 관련 코드 읽고 버그 원인 정확히 짚기
2. **원인 설명**: 왜 발생했는지 한 줄로 설명
3. **수정**: 최소한의 변경으로 고치기 (불필요한 리팩토링 금지)
4. **확인**: 수정 후 같은 버그가 다른 곳에도 있는지 체크 (특히 필터 로직, RS 계산 경계조건)

주요 파일:
- `screening.py` — 메인 Streamlit 앱 (탭 + UI)
- `screening_core.py` — RS 계산, 필터링, 랭킹
- `us_data_client.py` — 미국주식 데이터 API (yfinance/FDR)
- `us_ticker_mapping.py` — 티커 ↔ 한글명 매핑
- `china_stock_filter.py` — 중국기업 필터
- `cache.py` — 시세/메타 캐시 (SQLite or Parquet)
- DB: `screening_cache.db`
