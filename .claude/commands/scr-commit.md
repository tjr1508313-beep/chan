변경된 파일을 분석해서 git commit을 수행해줘.

1. `git diff` 와 `git status` 로 변경사항 파악
2. `.claude/plans/PLAN.md` 를 읽어서 이번 작업이 어떤 Phase/항목과 연관됐는지 파악
3. 아래 형식으로 커밋 메시지 작성 후 커밋:

```
[한 줄 요약]

# 계획서 연관 항목
- Phase N, 작업 N-N: ...

# 코드 핵심 변경
- ...

# 주의/문제될 수 있는 부분
- ...

# 다음 작업 제안
- ...

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

4. 변경된 파일 모두 스테이징 후 커밋 (단, `.env`, 비밀번호, API 키 파일은 절대 포함하지 말 것)
5. 커밋 완료 후 `git log --oneline -3` 으로 결과 확인
