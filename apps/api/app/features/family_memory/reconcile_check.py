"""파생 데이터 정리 점검(운영용 CLI, 읽기 전용): `python -m app.features.family_memory.reconcile_check`.

동의가 없거나 가족 기능이 꺼진 쪽에 임베딩·추억 후보·작업이 **남아 있는지** 센다. 모두 0 이면 종료 코드 0, 하나라도 남아 있으면 1(정리가 실패해 남았거나 대조 정리 워커가 돌지 않는다는 뜻),
DB 에 연결하지 못하거나 표가 없으면 2. cron·모니터링에서 종료 코드로 감지한다. 사진 내용·id·사용자 정보는 출력하지 않고 개수만 낸다. 아무것도 지우거나 바꾸지 않는다
(지우는 일은 워커의 `reconcile` 이 한다)."""

import json
import sys

from app.shared.db import SessionLocal

from . import reconcile

EXIT_OK = 0
EXIT_PENDING = 1
EXIT_ERROR = 2


def main() -> int:
    try:
        with SessionLocal() as db:
            summary = reconcile.pending_summary(db)
    except Exception as exc:  # noqa: BLE001  내용이 출력에 남지 않게 종류만 적는다
        print(json.dumps({"ok": False, "error": type(exc).__name__}))
        return EXIT_ERROR
    pending = sum(summary.values())
    print(json.dumps({"ok": pending == 0, "pending": pending, **summary}))
    return EXIT_OK if pending == 0 else EXIT_PENDING


if __name__ == "__main__":
    sys.exit(main())
