"""검색 품질 실행기(CLI) 안전 점검: 잘못된 run-id 와 이미 있는 결과 폴더는 앱을 띄우기 전에 거부한다."""

from evals.search_quality import cli


def test_a_bad_run_id_is_refused_before_anything_starts(tmp_path, capsys):
    assert cli.main(["--run-id", "../escape", "--out", str(tmp_path)]) == 2
    assert not list(tmp_path.iterdir())


def test_an_existing_result_folder_is_never_overwritten(tmp_path, capsys):
    (tmp_path / "keep").mkdir()
    (tmp_path / "keep" / "report.json").write_text("{}", encoding="utf-8")
    assert cli.main(["--run-id", "keep", "--out", str(tmp_path)]) == 2
    assert (tmp_path / "keep" / "report.json").read_text(encoding="utf-8") == "{}"


def test_results_are_ignored_by_git():
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    ignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert "apps/api/evals/search_quality/results/" in ignore
