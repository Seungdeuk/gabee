"""검색 품질 기준선 실행기(실모델 0회): `python -m evals.search_quality.cli --run-id <이름>`.

임시 SQLite·임시 데이터 폴더·API 키 없음·네트워크 차단으로 앱을 띄워 합성 월드를 만들고 `runner.run` 결과를
`evals/search_quality/results/<run-id>/report.json` 에 저장한다(이 폴더의 개별 실행 결과는 Git 이 추적하지 않는다).
공용 DB·운영 DB 에는 연결하지 않는다: 앱을 불러오기 전에 환경변수를 임시 SQLite 로 정하고, 불러온 뒤에도 `env.check_process_boundary` 로 다시 확인한다.
"""

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _isolate(root: Path) -> None:
    """앱을 불러오기 전에 임시 SQLite·폴더만 쓰고 외부 서비스 키를 비운다."""
    os.environ["DATABASE_URL"] = f"sqlite:///{root.as_posix()}/sq.db"
    os.environ["DATA_DIR"] = str(root)
    os.environ["ANTHROPIC_API_KEY"] = ""
    os.environ["JWT_SECRET"] = "search-quality-eval-only-secret-0123456789abcdef"
    os.environ["PRIVACY_NER_MODE"] = "off"
    os.environ["PRIVACY_NER_MODEL_DIR"] = ""
    for name in ("MAIL_BACKEND", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"):
        os.environ[name] = ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="sq-baseline")
    parser.add_argument("--out", default=None, help="결과 폴더(기본: evals/search_quality/results)")
    args = parser.parse_args(argv)
    if not _RUN_ID.fullmatch(args.run_id):
        print("run-id 는 영문·숫자·._- 만 쓴다", file=sys.stderr)
        return 2
    out_root = Path(args.out) if args.out else RESULTS
    target = out_root / args.run_id
    if target.exists():
        print(f"이미 있는 결과 폴더는 덮어쓰지 않는다: {target}", file=sys.stderr)
        return 2

    root = Path(tempfile.mkdtemp(prefix="gabee-sq-"))
    _isolate(root)
    from fastapi.testclient import TestClient

    from app.main import app
    from evals.agent_eval import env
    from evals.search_quality import runner, world

    with env.eval_process(root):
        env.check_process_boundary(root)
        with TestClient(app) as client:
            built = world.build(client)
            report = runner.run(built, run_id=args.run_id)
    target.mkdir(parents=True)
    (target / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(report["query_sets"], ensure_ascii=False, indent=2))
    print(
        f"violations={report['security_violations']} mismatches={len(report['expectation_mismatches'])} -> {target}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
