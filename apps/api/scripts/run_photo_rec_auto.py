"""찰칵 흔한 사진 자동 보충을 설정과 무관하게 한 번 실행한다(로컬 확인용).

    cd apps/api
    python -m scripts.run_photo_rec_auto

- `PIXABAY_API_KEY`·`ANTHROPIC_API_KEY` 가 설정돼 있어야 한다(값은 출력하지 않는다). 오늘 부족분만 채운다.
- 어느 DB 에 쓰는지(호스트)를 먼저 출력한다. 실제 Pixabay·AI 를 부르므로 비용이 든다(하루 목표 3장 기준 AI 호출 몇 번).
"""

import logging
import sys
from datetime import UTC, datetime

from sqlalchemy.engine import make_url

from app.features.play import photo_rec_auto
from app.shared.config import settings
from app.shared.db import SessionLocal, import_all_models


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"DB 호스트: {make_url(settings.database_url).host}")
    import_all_models()  # 모든 표를 불러와야 외래 키가 풀린다(서버는 시작할 때 한다)
    with SessionLocal() as db:
        result = photo_rec_auto.run_daily(db, datetime.now(UTC))
    if result.skipped:
        print(f"건너뜀: {result.skipped} (키가 설정돼 있는지 확인하세요)")
        return 1
    print(f"추가 {result.added} · 시도 {result.attempts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
