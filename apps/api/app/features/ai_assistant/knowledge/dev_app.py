# ruff: noqa: E402
"""로컬 SQLite 만 쓰는 시험용 서버(팀 DB 에 테이블을 만들지 않으려고 DATABASE_URL 을 고정한다).

  uvicorn app.features.ai_assistant.knowledge.dev_app:app --port 8001
그다음 http://localhost:8001/docs 에서 /ai-assistant/chat, /ai-assistant/knowledge/* 를 눌러 볼 수 있다
(가입 → 그룹 만들기 → 기록 넣기 → 채팅)."""

import os
from pathlib import Path

_DB = Path(__file__).resolve().parents[4] / "data" / "knowledge_dev.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB.as_posix()}"

from app.main import app  # noqa: F401
