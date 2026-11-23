# 찰칵 가비 추천 시드 마이그레이션 2건 — `pathlib` 위험도 검사 차단과 승인 검토 자료

> DB 담당자 승인용 검토 자료다. **이 문서와 이 PR 은 승인 표기(`unsafe-python-approved: PR #번호`)를 넣지 않는다.** 승인은 DB 담당자가 PR 리뷰에서 하고, 표기도 담당자의 승인 근거(PR 번호)를 확인한 뒤에 넣는다.

## 1. 무엇이 막히는가

`apps/api/scripts/migration_risk.py` 의 `unsafe-import` 검사가 아래 두 리비전의 `from pathlib import Path` 를 `block` 으로 본다(허용 import 목록에 `pathlib` 이 없다).
CI 의 api 작업(`tests/test_migration_risk.py::test_real_revisions_in_repo_have_no_blocking_findings`)이 이 때문에 실패한다. 병합된 release/1.3(#493)에서 이미 실패하는 상태다.

| 리비전 | 파일 | 막힌 줄 | 하는 일 |
|---|---|---|---|
| `b8e2f4a6c917` | `play_photo_rec_seed.py` | 17 | `alembic/seed_data/photo_rec/seed.json` 과 `img/*.jpg` 를 읽어 `play_photo_rec` 에 시드 행(사진 포함) 삽입 |
| `e6a1b3c5d792` | `play_photo_rec_seed_credit.py` | 14 | `alembic/seed_data/photo_rec/credits.json` 을 읽어 시드 행의 출처 칸 채움 |

## 2. 안전성 검토(코드 확인 결과)

- **읽는 파일**: 모두 저장소에 커밋된 `alembic/seed_data/photo_rec/` 아래 파일뿐이다(`Path(__file__).resolve().parents[1] / "seed_data" / "photo_rec"`). 크기는 합계 약 0.03MB(`seed.json` 21KB, `credits.json` 15KB, 사진 `img/`).
- **네트워크·프로세스·동적 실행**: 없다. 쓰는 import 는 `json`, `datetime`, `pathlib`, `sqlalchemy`, `alembic` 뿐이다.
- **쓰는 곳**: `play_photo_rec` 한 표뿐이다. 행 id 는 `seed<번호>` 로 정해져 있고 이미 있으면 건드리지 않는다(여러 번 실행해도 안전). 두 번째 리비전은 비어 있는 칸만 채운다.
- **되돌리기**: `downgrade` 는 시드로 넣은 행(`source=3`, id `seed%`)만 지우고, 두 번째 리비전은 출처 값만 비운다. 다른 행·표는 건드리지 않는다.
- **데이터 손실·위험 변경**: `destructive` 검사에는 걸리지 않는다(드롭·이름 변경·타입 변경 없음).
- **남는 위험(승인자가 알아야 할 점)**: `seed.json` 의 `image` 값(`img/001.jpg` 형태)을 경로에 이어 붙여 읽는다. 값은 커밋된 파일에서 오므로 지금은 안전하지만, 그 JSON 이 바뀌어 `../` 가 들어가면 저장소 밖 파일을 읽어 DB 에 넣을 수 있다. 리뷰(커밋된 시드 파일 변경 검토)가 방어선이다.

## 3. 승인이 필요한 근거

`CLAUDE.md` "공용 PostgreSQL 마이그레이션 규칙"과 `migration_risk.py` 에 따라, 허용 목록 밖 import 는 DB 담당자가 리뷰하고 리비전 docstring 에 `unsafe-python-approved: PR #<번호>` 를 적어야만 `warn` 으로 낮아진다.
Claude Code 는 이 승인 문구를 임의로 넣지 않으며, 승인 PR 번호를 추정하지 않는다.

## 4. 선택지(DB 담당자 결정)

| 안 | 내용 | 장단점 |
|---|---|---|
| A | 두 리비전 docstring 에 `unsafe-python-approved: PR #<승인 PR 번호>` 를 담당자가 추가 | 가장 작은 변경. 다만 적용된 리비전 파일을 고치는 것이라 "적용된 리비전은 수정하지 않는다" 규칙의 예외로 담당자가 판단해야 한다(docstring 만 바뀌고 리비전 id·동작은 같다). 공용 DB 에 이미 적용됐는지도 확인 필요 |
| B | 새 리비전으로 시드 방식을 바꾼다(파일 읽기 없이 데이터를 코드에 담는 등) | 검사는 통과하지만 사진 바이너리를 코드에 넣어야 해 크고, 이미 적용된 리비전은 그대로 남는다. 검사는 새 파일뿐 아니라 기존 두 파일도 계속 막는다 |
| C | `migration_risk.py` 허용 목록에 `pathlib` 추가 | **권하지 않는다.** 모든 마이그레이션에 파일 접근을 허용하게 되어 검사의 취지가 약해진다(이번 승인 범위에서도 제외) |

권고: A. 근거는 위 2번(읽는 파일이 커밋된 시드뿐, 네트워크·프로세스 없음, 되돌리기 안전)과 "남는 위험"의 방어선(시드 파일 변경 리뷰).

## 5. 확인이 필요한 사실(담당자)

- 두 리비전이 공용 PostgreSQL 에 이미 적용됐는지(`alembic_version`). 적용돼 있다면 A 는 docstring 변경만이라 DB 에 영향이 없다.
- 승인에 쓸 PR 번호.
