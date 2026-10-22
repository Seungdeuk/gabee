# 구현 현황: family-group (통합 인증·가족 구성원)

- 상태: 진행 중 (PR 4-A 스키마 완료, API·모바일은 아직)
- 담당: Seungdeuk (PR 4-A)
- 요구사항: docs/requirements/family-group.md

## 구현된 것

- **PR 4-A — DB 스키마 확장** (Alembic 리비전 `b6931fc30c66`, `355a1a748ec5` 위)
  - `users`에 `login_id`/`email`/`email_verified_at`/`password_hash` 추가(전부 nullable, 익명 계정은 NULL 유지).
  - `group_members`에 `role`(owner/admin/member, 그룹당 owner 최대 1명을 부분 유니크 인덱스로 강제)/`family_relation`/`family_relation_detail`/`display_name` 추가. 기존 행은 `groups.owner_id` 기준으로 `role` 백필.
  - `invites`에 서로게이트 `id`(UNIQUE, 기존 행도 백필)/`expires_at`/`max_uses`/`use_count` 추가. PK는 여전히 `code`, 기존 코드는 폐기하지 않음(폐기는 PR 4-D에서).
  - 신규 테이블 7개: `social_accounts`, `refresh_tokens`, `password_resets`, `email_verifications`, `member_nicknames`(그룹 멤버십을 참조하는 복합 FK), `join_requests`(pending 중복 방지 부분 유니크), `invite_attempts`.
  - `repository.add_group()`의 owner-role 버그 수정(그룹 생성자가 `member`로 저장되던 것을 `owner`로 수정) — 회귀 테스트 `test_create_group_assigns_invite_id_and_owner_role` 추가.
  - 기존 API 동작은 전혀 바뀌지 않음(회원가입/로그인/초대 참여 로직은 그대로).

## 남은 것

- PR 4-B: 로그인 ID/비밀번호 가입·로그인, Access/Refresh 토큰 발급 API.
- PR 4-C: Google/Kakao 소셜 로그인 연동 API.
- PR 4-D: 초대코드 보안 강화(관리자 승인, 레이트리밋, 만료/1회 정책) + 레거시 무제한 코드 폐기·자동 재발급.
- PR 4-E: 가족 관계·표시 이름·구성원별 별명 지정 API, owner/admin 권한 관리 API.
- PR 4-F: 위 기능들의 모바일 화면(로그인, 소셜 연동, 초대 승인, 가족 프로필).
