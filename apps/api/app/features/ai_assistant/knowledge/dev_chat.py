# ruff: noqa: E402
"""knowledge 시험용 터미널 채팅. 전처리·팀 DB 없이 가짜 기록으로 "저장 → 검색 → LLM 답"을 확인한다.

항상 이 PC 의 로컬 SQLite(`apps/api/data/knowledge_dev.db`)만 쓴다(.env 의 DATABASE_URL 은 무시).
ANTHROPIC_API_KEY 가 있으면 LLM 이 검색 함수를 불러 답하고, 없으면 검색 결과만 보여 준다.

사용(apps/api 에서):
  python -m app.features.ai_assistant.knowledge.dev_chat "이번 달 전기요금 얼마야?"
  python -m app.features.ai_assistant.knowledge.dev_chat          # 질문을 계속 입력(빈 줄이면 끝)
"""

import os
import sys
from pathlib import Path

_DB = Path(__file__).resolve().parents[4] / "data" / "knowledge_dev.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB.as_posix()}"

from sqlalchemy import func, select

from app.shared.config import settings
from app.shared.db import SessionLocal, init_db

from . import models, rag_chat, service
from .embedding import get_embedder
from .seed import seed_demo

GROUP, USER = "dev-group", "dev-user"


def _show(db, question: str) -> None:
    r = rag_chat.ask(db, GROUP, question)
    for c in r.tool_calls:
        print(f"  [함수] {c['name']} {c['input']}")
    print(f"가비({r.source}): {r.answer}")
    for s in r.sources:
        where = f" · {s['page']}" if s.get("page") else ""
        print(f"  [출처] {s['title']} ({s['kind_label']}{where}) {s.get('source_path') or ''}")


def main() -> None:
    init_db()
    with SessionLocal() as db:
        if not db.scalar(select(func.count()).select_from(models.KnowledgeItem)):
            print(f"가짜 기록 {seed_demo(db, GROUP, USER)}건을 넣었어요.")
        print(f"임베딩: {get_embedder().name}")
        if (n := service.reindex(db)) > 0:
            print(f"모델이 바뀌어 벡터 {n}개를 다시 만들었어요.")
        if not settings.anthropic_api_key:
            print(
                "ANTHROPIC_API_KEY 가 없어서 LLM 없이 검색 결과만 보여요. (apps/api/.env 에 넣어 주세요)"
            )
        questions = sys.argv[1:]
        if questions:
            for q in questions:
                print(f"\n질문: {q}")
                _show(db, q)
            return
        while q := input("\n질문> ").strip():
            _show(db, q)


if __name__ == "__main__":
    main()
