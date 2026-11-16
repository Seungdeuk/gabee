"""검색 색인 점검: 임베딩 모델 이름이 서버 설정과 DB 조각에서 어긋나 문서가 오류 없이 의미 검색에서 빠지는지 본다.

세 곳에서 쓴다 — 서버 시작 경고 로그(`log_startup`), 운영자 조회 API(router 의 /index-status), 재색인 도구(scripts.reindex_embeddings).
읽기 전용이고 결과에는 개수와 모델 이름만 있다(문서 내용·제목·가족 그룹 id·기록 id 는 싣지 않는다)."""

import logging
import threading
from typing import Any

from sqlalchemy.orm import Session

from app.shared.db import SessionLocal

from . import embedding
from . import repository as repo

logger = logging.getLogger("gabee.knowledge.index")


def model_folder_warnings(dialect: str, current_model: str) -> list[str]:
    """PostgreSQL 인데 기대 모델이 해시(모델 폴더를 못 찾음)면 알린다. SQLite 는 해시 임베더도 정상이다."""
    if dialect == "postgresql" and current_model.startswith("hashing-"):
        return [
            "경고: 모델 폴더를 찾지 못했어요(model.onnx 없음). 서버는 PostgreSQL 검색에서 이 설정으로 "
            "동작하지 못해요. EMBED_MODEL_DIR·DATA_DIR 을 서버와 같게 맞췄는지 확인하세요(데이터는 바뀌지 않았어요)."
        ]
    return []


def collect(db: Session, current_model: str, group_id: str | None = None) -> dict[str, Any]:
    """점검 숫자(개수만)."""
    return {
        "current_model": current_model,
        "by_model": repo.count_by_model(db, group_id),
        "stale_chunks": repo.count_stale(db, current_model, group_id),
        "stale_items": repo.count_stale_items(db, current_model, group_id),
        "missing_items": repo.count_items_missing_model(db, current_model, group_id),
    }


def warnings(dialect: str, report: dict[str, Any]) -> list[str]:
    """운영자가 알아야 할 점. 없으면 빈 목록."""
    out = model_folder_warnings(dialect, report["current_model"])
    if report["stale_chunks"]:
        out.append(
            f"현재 모델과 다른 조각이 {report['stale_chunks']:,}개 있어요. 영향받는 기록 {report['stale_items']:,}건 중 "
            f"{report['missing_items']:,}건은 의미 검색에서 완전히 빠져 있어요(오류 없이 검색 결과만 줄어요). "
            "재색인 도구(scripts.reindex_embeddings)로 점검하고, 서버와 같은 설정에서 다시 만드세요."
        )
    return out


_thread: threading.Thread | None = None


def start_startup_check() -> threading.Thread:
    """시작 점검을 백그라운드 스레드로 시작하고 기다리지 않고 돌아온다. 표가 잠겨 있어 질의가 오래 걸려도(예외가 아니라 대기)
    서버 시작이 멈추지 않게 하려는 것이다."""
    global _thread
    _thread = threading.Thread(
        target=lambda: log_startup(), name="knowledge-index-check", daemon=True
    )
    _thread.start()
    return _thread


def join_startup_check(timeout: float | None = 10) -> None:
    """시험용: 시작 점검 스레드가 끝나기를 기다린다."""
    if _thread is not None:
        _thread.join(timeout)


def log_startup() -> None:
    """한 번 점검해 로그로 알린다. 어떤 오류가 나도 예외를 밖으로 내보내지 않는다(DB 가 안 닿거나 표가 없을 수 있다)."""
    try:
        name = embedding.expected_model_name()  # 모델을 불러오지 않는다
        with SessionLocal() as db:
            report = collect(db, name)
            dialect = db.get_bind().dialect.name
        found = warnings(dialect, report)
    except Exception as exc:  # 예외 메시지에 접속 정보가 섞일 수 있어 클래스 이름만 남긴다
        logger.warning("검색 색인 점검하지 못했어요(%s). 서버는 계속 동작해요.", type(exc).__name__)
        return
    if found:
        for line in found:
            logger.warning("검색 색인 점검: %s (현재 모델 %s)", line, report["current_model"])
        return
    total = sum(report["by_model"].values())
    logger.info(
        "검색 색인 점검: 이상 없음(현재 모델 %s, 조각 %s개)", report["current_model"], f"{total:,}"
    )
