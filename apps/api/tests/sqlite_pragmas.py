"""pytest 가 만든 임시 SQLite 파일에만 속도 설정(PRAGMA)을 적용한다.

`client` 픽스처가 테스트마다 앱을 시작(87개 테이블 생성)하고 `drop_all` 하는데, 파일형 SQLite 는 그때마다 디스크에 동기화한다(fsync).
임시 파일이라 내구성이 필요 없으므로 `journal_mode=MEMORY`, `synchronous=OFF` 로 둔다(전체 시험 3시간 52분 → 25분, 통과·실패 동일).

운영·개발·공용 DB 에는 절대 적용하지 않는다. 아래 조건이 모두 맞을 때만 적용하고, 하나라도 다르면 아무것도 하지 않는다:
  - pytest 안에서 실행 중이다
  - 엔진이 SQLite 다
  - DB 파일이 `<시스템 임시 폴더>/gabee-test-*/test.db` 로, `conftest.py` 가 방금 만든 바로 그 임시 폴더의 파일이다
리스너는 이 엔진 객체 하나에만 붙고, 다른 SQLite 연결(다른 파일·다른 엔진)에는 영향이 없다.
"""

import sys
import tempfile
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine, make_url

PRAGMAS = (("journal_mode", "MEMORY"), ("synchronous", "OFF"))
TEMP_DIR_PREFIX = "gabee-test-"
DB_FILE_NAME = "test.db"


def is_pytest_temp_sqlite(url: str, temp_dir: str | Path) -> bool:
    """`url` 이 pytest 가 방금 만든 임시 폴더(`temp_dir`) 안의 SQLite 파일(`test.db`)이고 pytest 안에서 실행 중일 때만 True."""
    if "pytest" not in sys.modules:
        return False
    try:
        parsed = make_url(url)
    except Exception:  # noqa: BLE001 - 알 수 없는 URL 은 적용하지 않는다
        return False
    if parsed.get_backend_name() != "sqlite" or not parsed.database:
        return False
    temp = Path(temp_dir).resolve()
    if not temp.name.startswith(TEMP_DIR_PREFIX):
        return False
    if temp.parent != Path(tempfile.gettempdir()).resolve():
        return False
    return Path(parsed.database).resolve() == temp / DB_FILE_NAME


def apply(engine: Engine, temp_dir: str | Path) -> bool:
    """조건이 맞으면 이 엔진의 새 연결마다 PRAGMA 를 적용하는 리스너를 붙인다. 붙였으면 True."""
    if engine.dialect.name != "sqlite" or not is_pytest_temp_sqlite(
        engine.url.render_as_string(hide_password=False), temp_dir
    ):
        return False

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            for name, value in PRAGMAS:
                cursor.execute(f"PRAGMA {name}={value}")
        finally:
            cursor.close()

    return True
