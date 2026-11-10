"""DB 스키마 준비 상태 점검.

공용 DB 는 자동 배포(Alembic)로 갱신되므로, 새 마이그레이션이 들어 있는 코드가 DB 보다 먼저 실행되는
일시적 불일치가 생길 수 있다. 서버 전체를 죽이지 않고, **기능별로 실제 스키마를 점검**해서 준비되지 않은
기능의 API 만 503 으로 막는다(`schema_gate.py`).

- 판단 기준은 리비전 번호가 아니라 실제 스키마다: 각 기능의 SQLAlchemy 모델이 쓰는 테이블·컬럼이 DB 에 있고,
  코드가 모르는 'NOT NULL + 기본값 없음' 컬럼이나 NOT NULL 로 강화된 컬럼처럼 이 코드의 INSERT 를 깨뜨리는
  변경이 없을 때만 그 기능을 연다. DB 가 코드보다 앞서 있어도(알 수 없는 리비전) 호환된다고 가정하지 않고
  같은 점검을 통과해야 한다.
- 리비전 상태(뒤처짐·앞섬·알 수 없음·여러 head·없음)는 진단 정보다. 상태 확인 API(`/health/db`)와 로그에 쓴다.
- 결과는 짧게 캐시하고(준비됨 30초 / 준비 안 됨 2초) 만료되면 다시 점검하므로, 마이그레이션이 끝나면
  서버 재시작 없이 API 가 열린다.
- 로그·응답에는 비밀번호·접속 주소를 싣지 않는다(예외는 클래스 이름만 남긴다).
"""

import logging
import re
import threading
import time
from dataclasses import dataclass, field

from sqlalchemy import Table, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from . import db
from .config import settings

log = logging.getLogger(__name__)

CORE_FEATURE = "family_group"  # 모든 기능이 로그인·그룹 멤버십을 통해 의존한다
_FEATURE_RE = re.compile(r"^app\.features\.(\w+)\.")
_SHARED_RE = re.compile(r"^app\.shared\.(\w+)$")
# app/shared 의 공통 모델이 어떤 기능에서 쓰이는지. 등록되지 않은 공통 모델은 모든 기능의 전제(family_group)로 본다.
SHARED_MODEL_FEATURES = {
    "location_consent": ("family_group",),
    "ai_usage": ("family_chat", "ai_assistant"),  # AI 호출 한도·캐시·사용 기록
    "used_proposals": ("billing",),  # 에이전트 쓰기 제안 토큰의 사용 기록
    "notifications": ("notifications",),  # 알림함: 알림 기능만 쓴다
    "push_models": ("notifications",),  # 푸시 토큰·설정: 알림 기능만 쓴다
}


# 한 기능 안의 하위 기능(테이블 이름 접두사 → 하위 기능 이름). 이 접두사의 테이블은 상위 기능(schedule)이 아니라
# 하위 기능으로 따로 점검해, 준비 안 된 DB 에서 그 API 만 503 이 되게 한다(일정의 나머지 API 는 영향받지 않는다).
SUB_FEATURE_PREFIXES = {
    "events_check_": "schedule_check",  # 데일리 체크(schedule/check_router.py)
    "message_shares": "chat_share",  # 채팅 공유 카드(family_chat/share_router.py): 이 테이블이 없는 DB 에서도 소통의 나머지는 열린다
}


def feature_tables() -> dict[str, dict[str, Table]]:
    """기능 이름 → {테이블 이름: Table}. 각 기능 models.py 의 모델에서 자동으로 모은다."""
    db.import_all_models()
    features: dict[str, dict[str, Table]] = {}
    for mapper in db.Base.registry.mappers:
        module = mapper.class_.__module__
        table_name = mapper.local_table.name
        found = _FEATURE_RE.match(module)
        if found:
            owners = (found.group(1),)
        else:
            shared = _SHARED_RE.match(module)
            if not shared:
                continue
            owners = SHARED_MODEL_FEATURES.get(shared.group(1), (CORE_FEATURE,))
        for prefix, sub_feature in SUB_FEATURE_PREFIXES.items():
            if table_name.startswith(prefix):
                owners = (sub_feature,)
        for owner in owners:
            features.setdefault(owner, {})[table_name] = mapper.local_table
    return features


def _has_default(column) -> bool:
    return column.default is not None or column.server_default is not None


def table_problems(inspector, table: Table) -> list[str]:
    """이 코드의 모델과 실제 테이블이 맞지 않는 점. 비어 있으면 이 코드가 안전하게 쓸 수 있다."""
    if not inspector.has_table(table.name):
        return [f"테이블 {table.name} 없음"]
    actual = {c["name"]: c for c in inspector.get_columns(table.name)}
    problems = []
    for column in table.columns:
        found = actual.get(column.name)
        if found is None:
            problems.append(f"컬럼 {table.name}.{column.name} 없음")
        elif not found["nullable"] and column.nullable and not _has_default(column):
            problems.append(
                f"{table.name}.{column.name} 가 NOT NULL 로 강화됨(이 코드는 NULL 을 넣음)"
            )
    known = {c.name for c in table.columns}
    for name, found in actual.items():
        if name in known or found["nullable"]:
            continue
        if (
            found.get("default") is None
            and not found.get("autoincrement")
            and not found.get("identity")
        ):
            problems.append(f"{table.name}.{name}: 코드가 모르는 NOT NULL 컬럼(기본값 없음)")
    return problems


@dataclass
class SchemaStatus:
    checked_at: float
    db_connected: bool
    dialect: str | None = None
    db_revision: str | None = None
    code_head: str | None = None
    code_heads: list[str] = field(default_factory=list)
    # ready | not_applicable | behind | ahead_or_unknown | no_revision | invalid_revision_state
    # | multiple_heads | code_error | db_unavailable
    revision_state: str = "db_unavailable"
    pending_revisions: list[str] = field(default_factory=list)
    features: dict[str, dict] = field(default_factory=dict)  # {ready, reason, problems(로그 전용)}
    error: str | None = None

    @property
    def schema_ready(self) -> bool:
        return (
            self.db_connected
            and bool(self.features)
            and all(f["ready"] for f in self.features.values())
            and self.revision_state in ("ready", "not_applicable")
        )

    @property
    def status(self) -> str:
        if not self.db_connected:
            return "unavailable"
        return "ready" if self.schema_ready else "degraded"

    def feature_ready(self, feature: str) -> bool:
        """feature 와 그 전제(family_group)가 모두 준비됐는지."""
        needed = {feature, CORE_FEATURE}
        return self.db_connected and all(self.features.get(f, {}).get("ready") for f in needed)

    def public(self) -> dict:
        """상태 확인 API 응답: 접속 정보·테이블/컬럼 이름 같은 내부 정보는 싣지 않는다."""
        return {
            "status": self.status,
            "db_connected": self.db_connected,
            "dialect": self.dialect,
            "db_revision": self.db_revision,
            "code_head": self.code_head,
            "code_heads": self.code_heads,
            "revision_state": self.revision_state,
            "pending_revisions": self.pending_revisions,
            "schema_ready": self.schema_ready,
            "features": {
                n: {"ready": f["ready"], "reason": f["reason"]} for n, f in self.features.items()
            },
            "error": self.error,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.checked_at)),
        }


def _revision_info(connection, script) -> tuple[str | None, str, list[str]]:
    """(DB 리비전, 상태, 적용 대기 리비전)."""
    code_heads = script.get_heads()
    if len(code_heads) != 1:
        return None, "multiple_heads" if code_heads else "code_error", []
    head = code_heads[0]
    inspector = inspect(connection)
    if not inspector.has_table("alembic_version"):
        return None, "not_applicable" if connection.dialect.name == "sqlite" else "no_revision", []
    rows = [r[0] for r in connection.execute(text("SELECT version_num FROM alembic_version")).all()]
    if len(rows) != 1:
        return None, "no_revision" if not rows else "invalid_revision_state", []
    current = rows[0]
    if current == head:
        return current, "ready", []
    try:
        script.get_revision(current)
    except Exception:  # alembic CommandError: 이 코드가 모르는 리비전
        return current, "ahead_or_unknown", []
    pending = [r.revision for r in script.iterate_revisions(head, current) if r.revision != current]
    return current, "behind", pending[::-1]


def compute_status() -> SchemaStatus:
    now = time.time()
    try:
        with db.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            dialect = connection.dialect.name
            status = SchemaStatus(checked_at=now, db_connected=True, dialect=dialect)
            try:
                script = db._script_directory()
                status.code_heads = script.get_heads()
                status.code_head = status.code_heads[0] if len(status.code_heads) == 1 else None
                status.db_revision, status.revision_state, status.pending_revisions = (
                    _revision_info(connection, script)
                )
            except Exception as exc:  # alembic 이력 자체가 깨진 경우(순환 등)
                status.revision_state, status.error = "code_error", type(exc).__name__
            inspector = inspect(connection)
            for feature, tables in feature_tables().items():
                problems = [
                    p for table in tables.values() for p in table_problems(inspector, table)
                ]
                reason = None
                if problems:
                    missing = any("없음" in p and "NOT NULL" not in p for p in problems)
                    reason = "missing_schema" if missing else "incompatible_schema"
                status.features[feature] = {
                    "ready": not problems,
                    "reason": reason,
                    "problems": problems,
                }
            return status
    except (SQLAlchemyError, OSError) as exc:
        return SchemaStatus(checked_at=now, db_connected=False, error=type(exc).__name__)


class SchemaMonitor:
    """점검 결과 캐시. 만료되면 다음 요청에서 다시 점검한다(서버 재시작 불필요)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status: SchemaStatus | None = None
        self._last_summary: tuple | None = None
        self._last_run = 0.0

    def reset(self) -> None:
        with self._lock:
            self._status, self._last_summary, self._last_run = None, None, 0.0

    def status(self, force: bool = False) -> SchemaStatus:
        with self._lock:
            current = self._status
            now = time.monotonic()
            if current is not None:
                ttl = (
                    settings.schema_recheck_ready_seconds
                    if current.schema_ready
                    else settings.schema_recheck_not_ready_seconds
                )
                fresh = now - self._last_run < ttl
                too_soon = now - self._last_run < settings.schema_force_min_interval_seconds
                if (fresh and not force) or (force and too_soon):
                    return current
            self._status = compute_status()
            self._last_run = time.monotonic()
            self._log_transition(self._status)
            return self._status

    def _log_transition(self, status: SchemaStatus) -> None:
        summary = (
            status.db_connected,
            status.revision_state,
            status.db_revision,
            tuple(sorted(n for n, f in status.features.items() if not f["ready"])),
        )
        if summary == self._last_summary:
            return
        self._last_summary = summary
        if not status.db_connected:
            log.error(
                "DB 에 연결할 수 없습니다(%s). 연결이 복구되면 자동으로 다시 점검합니다.",
                status.error,
            )
        elif status.schema_ready:
            log.info("DB 스키마 준비 완료(리비전 %s).", status.db_revision)
        else:
            blocked = {n: f["problems"][:3] for n, f in status.features.items() if not f["ready"]}
            log.warning(
                "DB 스키마가 이 코드와 맞지 않습니다: 리비전 상태=%s, DB=%s, 코드=%s, 대기 리비전=%s, 막힌 기능=%s. "
                "해당 기능 API 만 503 을 반환하고 나머지는 계속 동작합니다. 공용 DB 라면 자동 배포(Deploy Shared DB)가 "
                "진행 중이거나 실패했을 수 있습니다.",
                status.revision_state,
                status.db_revision,
                status.code_head,
                status.pending_revisions,
                blocked,
            )


monitor = SchemaMonitor()
