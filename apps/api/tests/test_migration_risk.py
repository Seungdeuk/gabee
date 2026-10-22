"""scripts/migration_risk.py — 파괴적 변경·제약 강화 정적 검사."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import migration_risk as risk  # noqa: E402

HEADER = '"""{doc}"""\nfrom alembic import op\nimport sqlalchemy as sa\nrevision = "x1"\ndown_revision = None\n'


def scan(body: str, doc: str = "test") -> list[risk.Finding]:
    source = (
        HEADER.format(doc=doc)
        + "def upgrade():\n"
        + "\n".join("    " + ln for ln in body.splitlines())
    )
    return risk.scan_source(source, "x1")


def codes(findings, severity=None):
    return sorted(f.code for f in findings if severity in (None, f.severity))


def test_additive_migration_is_clean():
    body = 'op.create_table("t", sa.Column("id", sa.String(), nullable=False))\nop.add_column("users", sa.Column("x", sa.String(), nullable=True))'
    assert scan(body) == []


def test_drop_table_and_column_are_blocked():
    found = scan('op.drop_table("old")\nop.drop_column("users", "name")')
    assert codes(found, "block") == ["drop_column", "drop_table"]


def test_rename_and_type_change_are_blocked():
    found = scan(
        'op.alter_column("users", "a", new_column_name="b")\nop.alter_column("users", "c", type_=sa.Integer())'
    )
    assert codes(found, "block") == ["alter-type", "rename-column"]


def test_destructive_sql_is_blocked():
    assert codes(scan('op.execute("TRUNCATE users")'), "block") == ["destructive-sql"]
    assert codes(scan('op.execute(sa.text("DELETE FROM users"))'), "block") == ["destructive-sql"]


def test_non_transactional_changes_are_blocked():
    assert codes(
        scan('op.create_index("i", "t", ["c"], postgresql_concurrently=True)'), "block"
    ) == ["concurrently"]
    assert codes(scan("with op.get_context().autocommit_block():\n    pass"), "block") == [
        "autocommit-block"
    ]
    assert "non-transactional-sql" in codes(
        scan("op.execute(\"ALTER TYPE mood ADD VALUE 'x'\")"), "block"
    )


def test_destructive_approved_marker_downgrades_to_warning():
    found = scan(
        'op.drop_column("users", "name")', doc="drop old column\n\ndestructive-approved: PR #123"
    )
    assert risk.blocking(found) == []
    assert codes(found, "warn") == ["drop_column"]


def test_marker_without_pr_number_does_not_count():
    found = scan('op.drop_column("users", "name")', doc="destructive-approved: yes")
    assert codes(risk.blocking(found)) == ["drop_column"]


def test_constraint_tightening_on_existing_tables_only_warns():
    body = 'op.alter_column("users", "role", nullable=False)\nop.create_unique_constraint("u", "users", ["email"])\nop.add_column("users", sa.Column("z", sa.String(), nullable=False))'
    found = scan(body)
    assert risk.blocking(found) == []
    assert codes(found, "warn") == ["add-not-null", "create_unique_constraint", "not-null"]


def test_constraints_on_tables_created_in_same_revision_are_ignored():
    body = 'op.create_table("fresh", sa.Column("id", sa.String(), nullable=False))\nop.create_unique_constraint("u", "fresh", ["id"])\nop.alter_column("fresh", "id", nullable=False)'
    assert scan(body) == []


def test_missing_upgrade_is_blocked():
    found = risk.scan_source("revision = 'x'\n", "x1")
    assert codes(found, "block") == ["no-upgrade"]


def test_real_revisions_in_repo_have_no_blocking_findings():
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    for path in sorted(versions.glob("*.py")):
        assert risk.blocking(risk.scan_file(path, path.stem)) == [], path.name


def test_real_auth_revision_is_flagged_for_old_code_incompatibility_but_not_blocked():
    """PR 4-A 리비전은 기존 테이블 NOT NULL/UNIQUE 강화를 포함한다 — 경고로 감지되지만 막지는 않는다."""
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    path = next(versions.glob("b6931fc30c66_*.py"))
    found = risk.scan_file(path, "b6931fc30c66")
    assert risk.blocking(found) == []
    assert {"not-null", "create_unique_constraint"} <= {
        f.code for f in found if f.severity == "warn"
    }
