"""Persistent, verified copies of files dropped into the local GUI."""

import hashlib
import json
import os
import uuid
from pathlib import Path, PureWindowsPath

from svp_alignment.profiles.counting_stars import ROOT


_EXTENSIONS = {"svp": ".svp", "txt": ".txt", "wav": ".wav"}


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class UploadStore:
    """Own immutable upload copies, provenance, and their project-local lifetime."""

    def __init__(self, root=ROOT):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("업로드를 저장할 프로젝트 폴더가 없습니다.")
        self.storage = self.root / "work" / "uploads"

    @staticmethod
    def _extension(kind):
        try:
            return _EXTENSIONS[kind]
        except (KeyError, TypeError) as error:
            raise ValueError("업로드 종류는 svp, txt, wav 중 하나여야 합니다.") from error

    @staticmethod
    def _filename(source):
        original = getattr(source, "orig_name", None)
        name = original if isinstance(original, str) and original.strip() else Path(source).name
        # A browser filename must be one portable filename, never a path.
        if (not name or name in {".", ".."} or name != name.strip()
                or name.endswith(".") or PureWindowsPath(name).is_reserved()
                or any(ord(char) < 32 or char in '<>:"/\\|?*' for char in name)):
            raise ValueError("원본 파일 이름에 경로나 사용할 수 없는 문자가 있습니다.")
        return name

    def _guard(self, path):
        path = Path(path)
        resolved = path.resolve()
        if (not resolved.is_relative_to(self.root)
                or resolved != path.absolute()):
            raise ValueError("업로드 저장 경로에 프로젝트 외부 경로나 링크를 사용할 수 없습니다.")
        return resolved

    def save(self, source, kind):
        """Copy one dropped file without modifying its source or existing uploads."""
        extension = self._extension(kind)
        if source is None or not isinstance(source, (str, os.PathLike)):
            raise ValueError("업로드할 파일이 필요합니다.")
        filename = self._filename(source)
        if Path(filename).suffix.lower() != extension:
            raise ValueError(f"{extension} 파일을 업로드해 주세요.")
        supplied = Path(source)
        if supplied.is_symlink():
            raise ValueError("업로드 원본은 일반 파일이어야 합니다.")
        original = supplied.resolve(strict=True)
        if not original.is_file():
            raise ValueError("업로드 원본 파일을 찾을 수 없습니다.")
        before = _digest(original)

        storage = self._guard(self.storage)
        storage.mkdir(parents=True, exist_ok=True)
        self._guard(storage)
        upload_id = str(uuid.uuid4())
        target = self._guard(storage / upload_id)
        staging = self._guard(storage / (".upload-" + upload_id))
        staging.mkdir(exist_ok=False)
        try:
            self._guard(staging)
            copied = self._guard(staging / filename)
            with original.open("rb") as incoming, copied.open("xb") as outgoing:
                for block in iter(lambda: incoming.read(1024 * 1024), b""):
                    outgoing.write(block)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            copied_hash = _digest(copied)
            if before != copied_hash or before != _digest(original):
                raise ValueError("업로드 중 원본이 변경되었거나 복사 검증에 실패했습니다.")
            metadata = {
                "original_name": filename,
                "kind": kind,
                "source_sha256": before,
                "copied_sha256": copied_hash,
                "size": copied.stat().st_size,
            }
            manifest = self._guard(staging / "manifest.json")
            with manifest.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(metadata, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._guard(staging)
            self._guard(target)
            if target.exists():
                raise FileExistsError("기존 업로드 폴더를 덮어쓰지 않습니다.")
            staging.rename(target)
        except BaseException:
            # Only files created by this call can be removed after a failed copy.
            try:
                self._guard(staging)
                for name in (filename, "manifest.json"):
                    self._guard(staging / name).unlink(missing_ok=True)
                staging.rmdir()
            except (OSError, RuntimeError, ValueError):
                pass
            raise
        return str(target / filename)

    def managed(self, path, kind):
        """Check a persisted file and its provenance before restoring a GUI input."""
        try:
            extension = self._extension(kind)
            if not isinstance(path, (str, os.PathLike)):
                return False
            candidate = Path(path)
            if not candidate.is_absolute():
                return False
            storage = self._guard(self.storage)
            candidate = self._guard(candidate)
            relative = candidate.relative_to(storage)
            if len(relative.parts) != 2 or candidate.suffix.lower() != extension:
                return False
            parsed = uuid.UUID(relative.parts[0])
            if parsed.version != 4 or str(parsed) != relative.parts[0]:
                return False
            if not candidate.is_file():
                return False
            manifest = self._guard(candidate.parent / "manifest.json")
            if not manifest.is_file() or manifest.stat().st_size > 4096:
                return False
            metadata = json.loads(manifest.read_text(encoding="utf-8"))
            if (not isinstance(metadata, dict)
                    or metadata.get("original_name") != candidate.name
                    or metadata.get("kind") != kind
                    or metadata.get("size") != candidate.stat().st_size
                    or metadata.get("source_sha256") != metadata.get("copied_sha256")):
                return False
            return _digest(candidate) == metadata.get("copied_sha256")
        except (OSError, RuntimeError, TypeError, ValueError):
            return False
