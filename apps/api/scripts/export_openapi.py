"""서버 코드에서 API 명세(docs/contracts/openapi.json)를 생성한다."""

import json
from pathlib import Path

from app.main import app

OUT = Path(__file__).resolve().parents[3] / "docs" / "contracts" / "openapi.json"
OUT.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {OUT}")
