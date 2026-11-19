# AI 추억 동의·설정 (family_memory) — 구현 현황

요구사항: `docs/requirements/auto-memory.md`(자격·단계), ADR 0020(동의·자체 서버), ADR 0021(노출 정책). 동의·철회·삭제의 구현용 요구사항은 `docs/requirements/auto-memory-consent.md`(문서 PR #446).

## 지금 되는 것 (PR1, 2026-11-18)

**동의 기록과 분석 자격 판정만 있다. 이미지 분석·작업 큐·워커·추억 카드·앱 화면은 없고, 서버 스위치는 기본 꺼짐이라 켜지 않는 한 아무 일도 일어나지 않는다.**

| 기능 | 내용 |
|---|---|
| 서버 스위치 | 환경변수 `FAMILY_MEMORY_ENABLED`(기본 false). 꺼져 있으면 가족 활성화·동의를 새로 받지 않고 모든 사진이 분석 자격 없음(`server_off`). 제외·철회는 항상 가능 |
| 가족 활성화 | `GET/PUT /family-memory/settings`. 켜고 끄는 건 소유자·관리자만(member 403 `not_manager`). 끄면 정리 훅(`memory_hooks.family_disabled`)을 같은 트랜잭션에서 부른다 |
| 업로더 동의·철회 | `PUT /family-memory/consent`(본인만). 철회는 요청 안에서 즉시 효력(`withdrawn_at`), 두 번 보내도 같음. 정리 훅(`member_withdrawn`)이 실패하면 철회도 롤백 |
| 소급 분석 동의 | `PUT /family-memory/consent/retro`. 기본 동의와 별개·기본 없음, 기본 동의가 유효할 때만 켜짐, 철회·재동의 때 사라짐. **이 PR 에서는 기록만 하고 소급 분석 경로는 없다** |
| 사진별 제외 | `PUT /family-memory/photos/{attachment_id}/exclusion`. 업로더 본인만(남의 가족 전체방 사진 403, 다른 가족·남의 1:1 방 사진 404). 타임라인 제외(`chat_photo_checks`)와 별개 |
| 자격 판정 | `service.check_photo(db, attachment_id, retro=False)` → `Eligibility(eligible, reason)`. 서버 스위치 → 가족 활성 → 사진 존재 → 가족 전체방 → 업로더 동의 → (소급이면 소급 동의) → 제외 아님 → 판별 상태 `photo`(E0). 모르면 자격 없음 |
| 정리 | 가족 나가기: `member_exit` 훅으로 그 사람 동의 즉시 종료(같은 트랜잭션, 실패하면 나가기도 취소). 사진 삭제: `shared/memory_hooks` 로 제외 기록 삭제(실패해도 삭제 성공). 가족 삭제: 세 표 모두 `group_id` 열이 있어 `group_purge` 가 지움 |
| 기본값 | 가족 설정 행이 없으면 꺼짐, 동의 행이 없으면 미동의. 새로 들어온 구성원은 미동의로 시작 |

## 지키는 것
- `ai_group_settings`(대화 분석 동의)와 `chat_photo_checks`(사진 판별 상태, D-13)를 읽거나 쓰지 않는다(자격 판정은 판별 상태를 읽기만 한다).
- 사진 내용·라벨·임베딩·파일 경로를 저장·로그하지 않는다(이 PR 에는 그런 데이터가 없다).
- 동의 기록 보관 기간은 미결정이라 지우는 배치를 만들지 않았다. 가족을 나간 사람의 동의 행은 `withdrawn_at` 만 채우고 남긴다.

## 아직 없는 것 (이후 PR, 별도 승인)
- 앱 화면(동의 안내·스위치·사진 제외 버튼) — PR7 또는 별도 화면 PR.
- 작업 큐·워커·SigLIP2·카드 생성·게시(PR2 이후). 철회 시 파생 데이터(임베딩 등) 삭제는 지금은 지울 데이터가 없어 훅만 있다.
- E1(`unsure` 포함 자동 게시): 독립 안전성 평가와 별도 정책 승인 전에는 열지 않는다.
- 미결정: 동의 기록 보관 기간, 24시간 삭제 목표 확정, 백업 만료·복원 시 재삭제 절차, 원본 채팅 사진의 탈퇴 처리, 소급 분석 화면·고지.

## 시험
`apps/api/app/features/family_memory/tests/test_family_memory.py` — 기본 꺼짐, 서버 스위치, owner/admin/member 권한, 가족 간 격리, 동의·철회 멱등, 소급 동의 분리, 사진별 제외(본인만), 자격 판정 표, D-13·`ai_group_settings` 불변, 훅 실패 롤백, 가족 나가기·사진 삭제·가족 삭제 정리, 로그.
