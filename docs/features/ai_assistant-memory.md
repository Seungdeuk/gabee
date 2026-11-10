# 구현 현황: 가비의 기억

- 상태: 구현 완료. 마이그레이션 `30ffd13a359a` 필요(코드 배포 전에 DB 먼저, 공용 DB 는 DB 담당자).
- 요구사항: [docs/requirements/ai_assistant-memory.md](../requirements/ai_assistant-memory.md)

## 구조

- 서버: `ai_assistant/memories.py`(저장·삭제), 표 `assistant_memories`, 메인 채팅 도구 `remember`·`update_memory`·`forget`, API `GET·DELETE /ai-assistant/memories`, `PATCH·DELETE /ai-assistant/memories/{id}`.
- 메인 채팅: AI 채팅 탭(`audience=me`)에서만 도구와 기억 목록을 넘긴다. 목록은 시스템 안내에 들어가고 그 안의 지시는 따르지 않도록 적었다.
- 앱: 마이 > 가비의 기억(`screens/MemoriesScreen.js`, 라우트 `/memories`).

## 한계

- 건강·고민·집 주소를 한 번 더 묻는 것과, 문서를 보고 저장하지 않는 것은 프롬프트 지시라 코드로 보장되지 않는다. 고위험 번호 거절만 코드가 한다.
- 내용은 암호화하지 않는다.
- 구성원이 가족을 나가도 줄은 남는다(읽을 수는 없다).
