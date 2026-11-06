# 기능: 공지사항 (notices)

## 목적
서비스 관리자가 가비 사용자 모두에게 서비스 소식(업데이트·안내·점검)을 알린다. 가족 데이터가 아니다.

## 결정 (2026-11-05)
- 담는 것: **제목, 종류(칩), 내용**. 종류는 `update`(업데이트)·`info`(안내)·`maintenance`(점검). 고정·임시저장은 두지 않는다(쓰면 바로 공개).
- 새 글 표시: **폰에만 기억**한다(열어 본 공지 id 를 AsyncStorage 에 저장). 서버에 읽음 기록을 남기지 않는다. 폰을 바꾸면 다시 '새 글'로 보인다.
- 알림: 새 공지를 올려도 **알림을 보내지 않는다**(나중에 따로 정한다).
- 앱 화면: 더보기 › 공지사항. 칩(전체·업데이트·안내·점검)으로 거르고, 누르면 같은 화면에서 내용을 연다(시안: 서비스 어드민 캔버스).

## API
- `GET /notices` (로그인한 사용자, 가족 없어도 됨): 최근순 최대 100건 `{rows: [{id, category, title, body, created_at, updated_at}]}`. 쓴 관리자는 담지 않는다.
- 서비스 관리자(통합관리자, `require_operator("admin")`):
  - `GET /admin/service/notices`: 최근순 최대 200건
  - `POST /admin/service/notices`: `{category, title(1~100자), body(1~5000자)}` → 201 + 그 공지
  - `PUT /admin/service/notices/{notice_id}`: 같은 본문으로 통째로 고친다 → 204, 없으면 404
  - `DELETE /admin/service/notices/{notice_id}`: 지운다(되돌릴 수 없음) → 204, 없으면 404
- `notices` 표가 없는 DB 에서는 공지 경로만 503(`schema_ready("notices")`).

## 데이터
- 새 표 `notices`(id, category, title, body, created_by, created_at, updated_at). 리비전 `7d2e4a9c1b38`(새 표만 추가, expand). 배포 순서는 DB 반영 → 서버 배포.
