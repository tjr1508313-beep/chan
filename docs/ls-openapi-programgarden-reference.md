# LS OpenAPI 참고 자료: Programgarden Finance

## 원본 링크
- GitHub finance 패키지: https://github.com/programgarden/programgarden/tree/main/src/finance
- Finance guide: https://github.com/programgarden/programgarden/blob/main/docs/finance_guide.md
- Raw guide: https://raw.githubusercontent.com/programgarden/programgarden/main/docs/finance_guide.md

## 왜 저장해두는가
Programgarden Finance는 LS증권 OpenAPI를 Python 친화적인 모듈 구조로 감싼 예제/문서다.
우리 프로젝트에서 LS증권 TR을 추가하거나 응답 블록명을 확인할 때 다음 용도로 참고한다.

- LS OAuth 로그인/토큰 흐름 확인
- 국내주식 TR 코드 분류 확인
- 업종/테마 관련 TR 후보 확인
- 호출 한도/응답 코드 처리 방식 참고
- 동기/비동기 호출 구조 참고

## 우리 프로젝트에서 특히 볼 부분
- 업종/테마
  - `t1511`: 업종현재가
  - `t1516`: 업종종목조회
  - `t1531`: 테마종목
  - `t1532`: 테마그룹
  - `t1537`: 테마별종목
- 시장/종목 정보
  - `t1102`: 주식현재가/시세
  - `t8407`: 복수종목시세
  - `t8454`: 멀티현재가
  - `t1422`/`t1442`: 관리/이상종목 후보로 과거 검토했으나, 우리 실증에서는 목적에 맞지 않아 현재 위험종목 필터는 FDR `Dept` 기반이다.
- 랭킹
  - `t1444`: 시가총액상위
  - `t1463`: 거래대금상위
  - `t1481`: 가격급등락
  - `t1482`: 신고/신저

## 현재 우리 코드와의 연결
- 한국 섹터 매핑 생성은 `screening/ls_sector.py`와 `scripts/build_kr_sector_map_ls.py`가 담당한다.
- 현재 적용된 LS 업종 경로는 공식 LS REST `/indtp/market-data`이며, `t8424` 전체업종과 `t1516` 업종별종목시세를 사용한다.
- `data/kr_sector_map.csv`는 LS `ls-industry` 행과 기존 `name-rule` 행을 병합한 결과다.

## 주의사항
- Programgarden 저장소 라이선스는 AGPL-3.0이다. 코드를 복사/벤더링하지 말고, TR 구조와 사용 흐름을 참고한 뒤 우리 코드로 새로 구현한다.
- 최종 구현 전에는 LS 공식 API 가이드와 라이브 응답으로 `tr_cd`, InBlock/OutBlock 필드, 연속조회 커서, 호출 제한을 다시 확인한다.
- API 키는 `.env`, Streamlit secrets, GitHub secrets에만 두고 문서/커밋에 남기지 않는다.
