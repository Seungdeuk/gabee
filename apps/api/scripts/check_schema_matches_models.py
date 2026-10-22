"""기존 PostgreSQL DB의 실제 스키마가 현재 SQLAlchemy 모델과 일치하는지 확인한다.

이미 테이블이 있는 개발 DB에 Alembic 이력을 도입하기 전(`alembic stamp head`),
"임의로 stamp 하지 말고 먼저 검증하라"는 요구사항을 위한 도구다.
불일치가 있으면 사람이 보고 판단할 수 있도록 표로 출력하고 종료 코드 1을 반환한다.

사용법 (apps/api 에서):
    DATABASE_URL=postgresql+psycopg://... python scripts/check_schema_matches_models.py
"""

import sys

from sqlalchemy import inspect

from app.shared.db import Base, engine, import_all_models


def check() -> bool:
    import_all_models()
    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names())
    ok = True

    for table in Base.metadata.sorted_tables:
        table_ok = True

        if table.name not in actual_tables:
            print(f"[MISMATCH] {table.name}: DB 에 테이블이 없음")
            ok = False
            continue

        actual_columns = {c["name"]: c for c in inspector.get_columns(table.name)}
        for column in table.columns:
            actual = actual_columns.get(column.name)
            if actual is None:
                print(f"[MISMATCH] {table.name}.{column.name}: DB 에 컬럼이 없음")
                table_ok = False
                continue
            if bool(actual["nullable"]) != bool(column.nullable):
                print(
                    f"[MISMATCH] {table.name}.{column.name}: nullable "
                    f"모델={column.nullable} DB={actual['nullable']}"
                )
                table_ok = False

        extra = set(actual_columns) - {c.name for c in table.columns}
        if extra:
            print(f"[MISMATCH] {table.name}: DB 에 모델에 없는 컬럼 {sorted(extra)}")
            table_ok = False

        actual_pk = set(inspector.get_pk_constraint(table.name)["constrained_columns"])
        expected_pk = {c.name for c in table.primary_key.columns}
        if actual_pk != expected_pk:
            print(f"[MISMATCH] {table.name}: PK 모델={expected_pk} DB={actual_pk}")
            table_ok = False

        if table_ok:
            print(f"[OK] {table.name}")
        else:
            ok = False

    return ok


if __name__ == "__main__":
    success = check()
    print(
        "\n스키마 일치: 모든 테이블이 모델과 같음"
        if success
        else "\n스키마 불일치 발견 - 위 내용을 확인하세요"
    )
    sys.exit(0 if success else 1)
