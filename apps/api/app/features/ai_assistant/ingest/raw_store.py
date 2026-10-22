"""원본 데이터 센터: 올라온 파일을 가공하지 않고 그대로 보관한다(가리기 전 원본이라 접근을 제한한다).

로컬 개발은 `DATA_DIR/raw/<group_id>/<sha256 앞 2자리>/<sha256><확장자>`. 같은 내용은 한 번만 저장된다.
운영 보관소(Supabase Storage 등)는 미정 — 같은 put/get/delete 모양으로 바꿔 끼운다.
"""

import re
from pathlib import Path

from pydantic import BaseModel

from app.shared.config import settings

_GROUP_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_EXT = re.compile(r"^\.[a-z0-9]{1,5}$")
_LABEL = re.compile(r"^[a-z0-9]{1,16}$")


class RawRef(BaseModel):
    path: str  # 원본 데이터 센터 안의 위치 (group_id/…)
    created: bool  # 이번에 새로 저장했으면 True, 같은 원본이 이미 있었으면 False


class LocalRawStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or settings.raw_dir or Path(settings.data_dir) / "raw")

    def _path(self, group_id: str, sha256: str, ext: str) -> Path:
        if not _GROUP_ID.match(group_id) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError("group_id 또는 sha256 형식이 올바르지 않아요")
        return self.root / group_id / sha256[:2] / f"{sha256}{ext if _EXT.match(ext) else '.bin'}"

    def put(self, group_id: str, sha256: str, ext: str, data: bytes) -> RawRef:
        return self._write(self._path(group_id, sha256, ext), data)

    def put_copy(self, group_id: str, sha256: str, label: str, ext: str, data: bytes) -> RawRef:
        """원본에서 만든 사본(화면용 등)을 원본 옆 `<sha256>.<label><확장자>` 에 둔다."""
        if not _LABEL.match(label) or not _EXT.match(ext):
            raise ValueError("사본 이름 또는 확장자 형식이 올바르지 않아요")
        return self._write(
            self._path(group_id, sha256, ext).with_name(f"{sha256}.{label}{ext}"), data
        )

    def _write(self, path: Path, data: bytes) -> RawRef:
        rel = path.relative_to(self.root).as_posix()
        if path.exists():
            return RawRef(path=rel, created=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)  # 쓰다 멈춰도 반쪽 파일이 남지 않게
        return RawRef(path=rel, created=True)

    def get(self, ref_path: str) -> bytes:
        return self._resolve(ref_path).read_bytes()

    def delete(self, ref_path: str) -> None:
        self._resolve(ref_path).unlink(missing_ok=True)

    def _resolve(self, ref_path: str) -> Path:
        path = (self.root / ref_path).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("원본 데이터 센터 밖의 경로예요")
        return path
