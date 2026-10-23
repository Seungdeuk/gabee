"""CI 용 Alembic 검증. 하위 명령:

    heads            리비전 체인의 head 가 정확히 1개인지 확인한다(DB 연결 없음).
    assert-empty     대상 DB 가 빈 상태인지 확인한다(읽기 전용).
    assert-at-head   DB 의 alembic_version 이 코드의 head 와 같은지 확인한다(읽기 전용).

assert-* 는 .github/workflows/ci-check.yml 의 api-postgres 서비스 DB 전용이다. 환경변수 플래그
(GITHUB_ACTIONS 등)는 신뢰하지 않고, 접속 정보가 CI 서비스 DB 와 정확히 일치할 때만 연결한다 —
호스트(localhost), 포트, DB 이름, 계정이 다르거나 URL 에 쿼리 옵션(?host= 등)이 붙어 있으면
연결하기 전에 거부하고, 연결한 뒤에도 실제 서버가 알려주는 DB 이름·계정을 다시 확인한다.
CI 서비스 DB 설정을 바꾸면 아래 상수도 함께 바꾼다.

사용법 (apps/api 에서):
    python scripts/check_alembic_migrations.py heads
    DATABASE_URL=postgresql+psycopg://gabee_ci:...@localhost:5432/gabee_ci \
        python scripts/check_alembic_migrations.py assert-empty
"""

import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import URL

API_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_HOSTS = ("localhost", "127.0.0.1")
EXPECTED_PORT = 5432
EXPECTED_DATABASE = "gabee_ci"
EXPECTED_USER = "gabee_ci"

# 빈 DB 판정에서 허용하는 확장(pgvector 이미지 기본 구성)
_ALLOWED_EXTENSIONS = {"plpgsql", "vector"}


def _script_directory(alembic_dir: Path | None = None) -> ScriptDirectory:
    cfg = Config()
    cfg.set_main_option("script_location", str(alembic_dir or API_ROOT / "alembic"))
    return ScriptDirectory.from_config(cfg)


def check_heads(alembic_dir: Path | None = None) -> bool:
    script = _script_directory(alembic_dir)
    heads = script.get_heads()
    if len(heads) == 1:
        print(f"[OK] Alembic head 1개: {heads[0]}")
        return True

    if not heads:
        print("[FAIL] Alembic head 가 없습니다 — 리비전 파일이 없거나 순환 참조입니다.")
        return False

    print(f"[FAIL] Alembic head 가 {len(heads)}개입니다 (정확히 1개여야 함):")
    for head in heads:
        rev = script.get_revision(head)
        print(f"  - {head}  (down_revision={rev.down_revision})  {Path(rev.path).name}")
    print(
        "\n여러 PR 이 같은 부모 리비전 위에 각자 마이그레이션을 추가하면 생깁니다.\n"
        "나중에 병합되는 쪽이 최신 main 을 받아 자기 리비전의 down_revision 을 "
        "main 의 현재 head 로 바꾸세요."
    )
    return False


def target_problems(url: URL) -> list[str]:
    """접속 정보가 CI 서비스 DB 와 다른 점을 모두 돌려준다(없으면 안전). DB 연결 없이 판단한다."""
    problems = []
    if url.get_backend_name() != "postgresql":
        problems.append(f"PostgreSQL 이 아닙니다: {url.get_backend_name()}")
    if url.host not in EXPECTED_HOSTS:
        problems.append(f"호스트는 {EXPECTED_HOSTS} 중 하나여야 합니다: {url.host}")
    if (url.port or 5432) != EXPECTED_PORT:
        problems.append(f"포트는 {EXPECTED_PORT} 여야 합니다: {url.port}")
    if url.database != EXPECTED_DATABASE:
        problems.append(f"DB 이름은 {EXPECTED_DATABASE!r} 여야 합니다: {url.database!r}")
    if url.username != EXPECTED_USER:
        problems.append(f"계정은 {EXPECTED_USER!r} 여야 합니다: {url.username!r}")
    if url.query:
        problems.append(
            f"URL 쿼리 옵션은 허용하지 않습니다(host 등을 덮어쓸 수 있음): {sorted(url.query)}"
        )
    return problems


def _guarded_engine():
    from app.shared.db import engine

    problems = target_problems(engine.url)
    if problems:
        print("[REFUSED] 접속 대상이 CI 서비스 DB 와 다릅니다 — 연결하지 않습니다:")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(2)

    from sqlalchemy import text

    with engine.connect() as conn:
        database, user = conn.execute(text("SELECT current_database(), current_user")).one()
    if (database, user) != (EXPECTED_DATABASE, EXPECTED_USER):
        print(f"[REFUSED] 실제 접속된 서버가 CI DB 가 아닙니다: database={database} user={user}")
        sys.exit(2)
    return engine


# 시스템 스키마와 확장(extension)이 만든 객체는 제외한다.
_USER_OBJECTS_SQL = """
SELECT 'relation' AS kind, n.nspname || '.' || c.relname AS name
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg\\_toast%' AND n.nspname NOT LIKE 'pg\\_temp%'
  AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass
                  AND d.objid = c.oid AND d.deptype = 'e')
UNION ALL
SELECT 'schema', nspname FROM pg_namespace
WHERE nspname NOT IN ('public', 'pg_catalog', 'information_schema')
  AND nspname NOT LIKE 'pg\\_toast%' AND nspname NOT LIKE 'pg\\_temp%'
UNION ALL
SELECT 'enum', n.nspname || '.' || t.typname
FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
WHERE t.typtype = 'e' AND n.nspname NOT IN ('pg_catalog', 'information_schema')
UNION ALL
SELECT 'function', n.nspname || '.' || p.proname
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass
                  AND d.objid = p.oid AND d.deptype = 'e')
UNION ALL
SELECT 'extension', extname FROM pg_extension
"""


def check_empty() -> bool:
    from sqlalchemy import text

    with _guarded_engine().connect() as conn:
        found = [
            f"{kind}:{name}"
            for kind, name in conn.execute(text(_USER_OBJECTS_SQL)).all()
            if not (kind == "extension" and name in _ALLOWED_EXTENSIONS)
        ]
    if found:
        shown = sorted(found)[:15]
        print(f"[FAIL] 테스트 DB 가 비어 있지 않습니다 (객체 {len(found)}개): {shown}")
        return False
    print("[OK] 테스트 DB 가 빈 상태입니다(테이블·뷰·시퀀스·스키마·타입·함수·확장 없음).")
    return True


def check_at_head() -> bool:
    from sqlalchemy import inspect, text

    head = _script_directory().get_current_head()
    engine = _guarded_engine()
    if "alembic_version" not in inspect(engine).get_table_names():
        print("[FAIL] alembic_version 테이블이 없습니다 — 마이그레이션이 적용되지 않았습니다.")
        return False
    with engine.connect() as conn:
        applied = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    if applied != [head]:
        print(f"[FAIL] 적용된 리비전 {applied} != 코드 head [{head!r}]")
        return False
    print(f"[OK] 적용된 리비전이 코드 head 와 같습니다: {head}")
    return True


COMMANDS = {"heads": check_heads, "assert-empty": check_empty, "assert-at-head": check_at_head}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        print(f"사용법: {sys.argv[0]} {{{'|'.join(COMMANDS)}}}")
        sys.exit(2)
    sys.exit(0 if COMMANDS[sys.argv[1]]() else 1)
