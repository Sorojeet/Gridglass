"""Where uploads live. One folder per upload, named by an unguessable id:

    DATA_DIR/<id>/
        meta.json        filename, format, sheets, steps, expiry
        original.<ext>   the uploaded file (kept so another sheet of a .xlsx/.xls can be chosen)
        source.parquet   the converted data every step reads from
        exports/         short-lived export files, deleted after download

No accounts in v1: the id is the key, and everything is deleted when it expires.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .engine.io import ingest

_ID = re.compile(r"^[A-Za-z0-9_-]{22}$")


class NotFound(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self, root: str | Path, retention_minutes: int = 60, max_bytes: int | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.retention = timedelta(minutes=retention_minutes)
        self.max_bytes = max_bytes

    # ------------------------------------------------------------------ paths
    def dir(self, file_id: str) -> Path:
        if not _ID.match(file_id or ""):
            raise NotFound(file_id)
        path = self.root / file_id
        if not (path / "meta.json").exists():
            raise NotFound(file_id)
        return path

    def source(self, file_id: str) -> Path:
        return self.dir(file_id) / "source.parquet"

    # ------------------------------------------------------------------ create
    def create(self, stream, filename: str, sheet: str | None = None) -> dict[str, Any]:
        """Save an upload stream, convert it, and return its metadata. Cleans up on failure."""
        file_id = secrets.token_urlsafe(16)  # 22 url-safe characters
        path = self.root / file_id
        path.mkdir()
        try:
            ext = Path(filename).suffix.lower()[:10]
            original = path / f"original{ext}"
            with open(original, "wb") as fh:
                shutil.copyfileobj(stream, fh, length=1024 * 1024)
            res = ingest(original, filename, path / "source.parquet", sheet=sheet, max_bytes=self.max_bytes)
            created = _now()
            meta = {
                "id": file_id,
                "filename": Path(filename).name[:255],
                "format": res.format,
                "sheets": res.sheets,
                "sheet": res.sheet,
                "rows": res.rows,
                "columns": res.columns,
                "steps": [],
                "created_at": created.isoformat(),
                "expires_at": (created + self.retention).isoformat(),
            }
            if res.format not in ("xlsx", "xls"):
                original.unlink()  # only .xlsx/.xls need the original, to switch sheets
            self._write_meta(path, meta)
            return meta
        except BaseException:
            shutil.rmtree(path, ignore_errors=True)
            raise

    def change_sheet(self, file_id: str, sheet: str) -> dict[str, Any]:
        path, meta = self.dir(file_id), self.meta(file_id)
        if meta["format"] not in ("xlsx", "xls"):
            from .engine import IngestError

            raise IngestError("Only .xlsx and .xls files have sheets.")
        original = next(path.glob("original.*"))
        tmp = path / "source.next.parquet"
        res = ingest(original, meta["filename"], tmp, sheet=sheet)
        os.replace(tmp, path / "source.parquet")
        meta.update(sheet=res.sheet, rows=res.rows, columns=res.columns, steps=[])  # old steps fit the old sheet
        self._write_meta(path, meta)
        return meta

    # ------------------------------------------------------------------ meta
    def meta(self, file_id: str) -> dict[str, Any]:
        path = self.dir(file_id)
        meta = json.loads((path / "meta.json").read_text())
        if datetime.fromisoformat(meta["expires_at"]) <= _now():
            shutil.rmtree(path, ignore_errors=True)
            raise NotFound(file_id)
        return meta

    def save_steps(self, file_id: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
        meta = self.meta(file_id)
        meta["steps"] = steps
        self._write_meta(self.dir(file_id), meta)
        return meta

    def _write_meta(self, path: Path, meta: dict[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(dir=path, prefix=".meta-", suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(meta, fh)
        os.replace(tmp, path / "meta.json")  # atomic: readers never see half a file

    # ------------------------------------------------------------------ exports & cleanup
    def export_path(self, file_id: str, ext: str) -> Path:
        out = self.dir(file_id) / "exports"
        out.mkdir(exist_ok=True)
        return out / f"{secrets.token_hex(8)}.{ext}"

    def delete(self, file_id: str) -> None:
        shutil.rmtree(self.dir(file_id), ignore_errors=True)

    def purge_expired(self) -> int:
        """Delete expired uploads and abandoned half-made folders. Returns how many were removed."""
        removed = 0
        cutoff = _now()
        for path in self.root.iterdir():
            if not path.is_dir():
                continue
            try:
                meta = json.loads((path / "meta.json").read_text())
                expired = datetime.fromisoformat(meta["expires_at"]) <= cutoff
            except (OSError, ValueError, KeyError):
                age = cutoff - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                expired = age > self.retention  # no valid meta: an upload that never finished
            if expired:
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
        return removed
