"""문서 조각의 임베딩을 지금 모델로 다시 만든다(모델 폴더 이름이 바뀌었거나 모델을 교체한 뒤).

    cd apps/api
    python -m scripts.reindex_embeddings                      # --check: 읽기 전용 점검(기본)
    python -m scripts.reindex_embeddings --apply              # 개수만 보여 주고(다시 만들 조각이 있으면) 종료 코드 2 로 끝난다(모델도 안 불러온다)
    python -m scripts.reindex_embeddings --apply --yes        # 실제로 다시 계산한다
    옵션: --batch-size N(기본 128) --group-id <가족 그룹> --limit N(시험용, 이번에 처리할 최대 조각 수)

- 공용 DB 는 DB 담당자만 실행한다. 먼저 --check 로 개수를 본다. Claude Code·개발자는 공용 DB 에 실행하지 않는다.
- 반드시 서버와 같은 EMBED_MODEL_DIR·DATA_DIR 로 실행한다(이름이 어긋난 채 --apply 하면 의미 검색이 오류 없이 0건이 된다).
  Docker 이미지에는 scripts/ 가 없어 컨테이너 안에서는 못 돌린다.
- 이 스크립트는 DATABASE_URL 이 가리키는 DB 를 그대로 쓴다. 어느 DB 인지(종류·호스트)를 먼저 출력한다.
- 출력과 오류에는 개수만 싣는다. 본문·그룹 id·기록 id·예외 메시지 원문은 찍지 않는다(오류는 클래스 이름만, 종료 코드 1).
- 모델 폴더의 ONNX 모델로만 --apply 할 수 있다. 해시 임베더(모델 파일이 없을 때의 대체)로는 거부한다.
- 배치마다 commit 하므로 중간에 멈춰도 이미 끝난 조각은 남고, 다시 실행하면 남은 것만 한다.
"""

import argparse
import sys
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.features.ai_assistant.knowledge import embedding, service
from app.features.ai_assistant.knowledge import repository as repo
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.errors import ApiError

DEFAULT_BATCH_SIZE = 128


def _parse(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="reindex_embeddings", description="임베딩 재색인")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="읽기 전용 점검(기본)")
    mode.add_argument("--apply", action="store_true", help="다시 계산(--yes 와 함께)")
    p.add_argument("--yes", action="store_true", help="--apply 실행을 확정한다")
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    p.add_argument("--group-id", default=None, help="이 가족 그룹만(선택)")
    p.add_argument("--limit", type=int, default=None, help="이번에 처리할 최대 조각 수(시험용)")
    return p.parse_args(argv)


SERVER_MATCH_WARNING = (
    "주의: 서버와 같은 설정에서 실행하는지 확인하세요(EMBED_MODEL_DIR·DATA_DIR). "
    "위 '현재 설정의 모델 이름'이 서버가 쓰는 이름과 다르면, 이대로 다시 만든 조각은 서버가 검색하지 않는 이름이 되어 "
    "오류 없이 의미 검색이 0건이 됩니다."
)


def model_warnings(dialect: str, current_model: str) -> list[str]:
    """PostgreSQL 인데 기대 모델이 해시(모델 폴더를 못 찾음)면 알린다. SQLite 는 해시 임베더도 정상이다."""
    if dialect == "postgresql" and current_model.startswith("hashing-"):
        return [
            "경고: 모델 폴더를 찾지 못했어요(model.onnx 없음). 서버는 PostgreSQL 검색에서 이 설정으로 "
            "동작하지 못해요. EMBED_MODEL_DIR·DATA_DIR 을 서버와 같게 맞췄는지 확인하세요(데이터는 바뀌지 않았어요)."
        ]
    return []


def collect_report(db: Session, current_model: str, group_id: str | None = None) -> dict[str, Any]:
    """점검 숫자(개수만)."""
    return {
        "current_model": current_model,
        "by_model": repo.count_by_model(db, group_id),
        "stale_chunks": repo.count_stale(db, current_model, group_id),
        "stale_items": repo.count_stale_items(db, current_model, group_id),
        "missing_items": repo.count_items_missing_model(db, current_model, group_id),
    }


def format_report(report: dict[str, Any], group_id: str | None = None) -> list[str]:
    lines = [
        f"범위: {'지정한 가족 그룹 1곳' if group_id else '전체'}",
        f"현재 설정의 모델 이름: {report['current_model']}",
        "모델별 조각 수:",
    ]
    by_model = report["by_model"]
    lines += [f"  - {name}: {n:,}" for name, n in sorted(by_model.items())] or ["  - (조각 없음)"]
    lines += [
        f"현재 모델과 다른 조각: {report['stale_chunks']:,}",
        f"영향받는 기록: {report['stale_items']:,}",
        f"의미 검색에서 완전히 빠진 기록: {report['missing_items']:,}",
    ]
    return lines


def _print_target() -> None:
    url = make_url(settings.database_url)
    print(f"대상 DB: {url.get_backend_name()} (호스트: {url.host or '-'})")


def _progress(done: int, total: int) -> None:
    print(f"reindex {done:,}/{total:,} ({done * 100 // total}%)", flush=True)


def _check(args: argparse.Namespace) -> int:
    name = embedding.expected_model_name()  # 모델을 불러오지 않는다
    with SessionLocal() as db:
        report = collect_report(db, name, args.group_id)
        warnings = model_warnings(db.get_bind().dialect.name, name)
    print("\n".join(format_report(report, args.group_id) + warnings))
    if report["stale_chunks"]:
        print("다시 만들려면 --apply --yes 를 붙여 실행하세요(공용 DB 는 DB 담당자만).")
    return 0


def _apply(args: argparse.Namespace) -> int:
    if args.batch_size < 1 or (args.limit is not None and args.limit < 1):
        print("--batch-size 와 --limit 은 1 이상이어야 해요.")
        return 1
    if not args.yes:  # 확인만: 모델을 불러오기 전에 끝낸다
        name = embedding.expected_model_name()
        with SessionLocal() as db:
            report = collect_report(db, name, args.group_id)
            warnings = model_warnings(db.get_bind().dialect.name, name)
        print("\n".join(format_report(report, args.group_id) + warnings))
        if not report["stale_chunks"]:
            print("다시 만들 조각이 없어요.")
            return 0
        print(SERVER_MATCH_WARNING)
        print("실제로 다시 계산하려면 --yes 를 함께 붙이세요(실행하지 않았어요).")
        return 2
    embedder = embedding.get_embedder()
    if not isinstance(embedder, embedding.OnnxE5Embedder):
        print(
            "ONNX 임베딩 모델을 불러오지 못해 중단했어요(지금은 해시 임베더). "
            "모델 폴더(EMBED_MODEL_DIR 또는 DATA_DIR/models/e5-small-ft 의 model.onnx)를 먼저 고치세요."
        )
        return 1
    with SessionLocal() as db:
        report = collect_report(db, embedder.name, args.group_id)
        print("\n".join(format_report(report, args.group_id)))
        if not report["stale_chunks"]:
            print("다시 만들 조각이 없어요.")
            return 0
        print(SERVER_MATCH_WARNING, flush=True)
        try:
            done = service.reindex(
                db,
                args.group_id,
                batch_size=args.batch_size,
                limit=args.limit,
                on_progress=_progress,
            )
        except ApiError as exc:
            if exc.code == "embedding_model_missing":
                print(
                    "embedding_model_missing: 모델 폴더를 먼저 고치세요(벡터 길이가 맞지 않아요)."
                )
                return 1
            raise
        remaining = repo.count_stale(db, embedder.name, args.group_id)
    print(f"완료: {done:,}개를 다시 만들었어요. 남은 조각 {remaining:,}개.")
    return 0


def main(argv: list[str]) -> int:
    args = _parse(argv)
    _print_target()
    try:
        return _apply(args) if args.apply else _check(args)
    except Exception as exc:  # 예외 메시지에 본문이 섞일 수 있어 클래스 이름만 낸다
        print(
            f"오류: {type(exc).__name__} (재색인 중이었다면 끝난 배치는 남아 있고, 다시 실행하면 이어서 해요)"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
