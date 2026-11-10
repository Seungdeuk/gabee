import pytest

from app.shared.config import settings


@pytest.fixture(autouse=True)
def play_data_dir(tmp_path, monkeypatch):
    """그림·사진은 시험마다 임시 폴더에만 쓴다(실제 data 폴더를 건드리지 않는다)."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    return tmp_path
