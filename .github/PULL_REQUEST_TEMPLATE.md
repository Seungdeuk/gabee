## 무엇을
<!-- 변경 내용 요약 -->

## 왜
<!-- 변경 이유 / 관련 요구사항 (docs/requirements/...) -->

## 테스트
- [ ] 서버: `uv run pytest`, `uv run ruff check .` 통과 (해당 시)
- [ ] 앱: `npm run lint` 통과 (해당 시)
- [ ] 직접 실행해서 확인함

## 참고
- [ ] API 변경 있음 → `docs/contracts/openapi.json` 갱신함 (하위 호환 깨짐 여부 아래에 기재)
- [ ] DB 변경 있음 → `supabase/migrations`에 파일 추가, `docs/contracts/db.md` 갱신함
- [ ] 내가 이 코드를 이해하고 설명할 수 있음
