# Copyright 2026 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Chunked host-to-runtime file transfer through NotebookSession.run_code."""

import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel

from cool_colab_mcp.constants import (
    RUNTIME_ROOT,
    UPLOAD_CHUNK_SIZE,
    UPLOAD_DIRS_ENV,
)
from cool_colab_mcp.errors import ToolFailed, fail
from cool_colab_mcp.sessions.session import NotebookSession


class UploadStatus(BaseModel):
    upload_id: str
    notebook_id: str
    source: str
    destination: str
    state: Literal["uploading", "complete", "failed", "cancelled"]
    bytes_sent: int
    size: int
    sha256: str
    error: str | None = None


class _UnsafeRuntimePath(ToolFailed):
    """An already-rejected runtime path that must never be used for cleanup."""


def allowed_upload_roots() -> tuple[Path, ...]:
    """Return resolved host roots configured through the upload allowlist."""
    value = os.environ.get(UPLOAD_DIRS_ENV, "")
    return tuple(
        Path(item).expanduser().resolve() for item in value.split(os.pathsep) if item
    )


def _host_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    roots = allowed_upload_roots()
    if not roots:
        raise fail(
            "user_action_required",
            f"Host uploads are disabled — configure {UPLOAD_DIRS_ENV} first.",
        )
    if not any(path == root or path.is_relative_to(root) for root in roots):
        raise fail(
            "invalid_input",
            "Host path is outside the configured upload directories.",
            path=str(path),
        )
    return path


def _runtime_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not path.is_absolute():
        path = PurePosixPath(RUNTIME_ROOT) / path
    if (
        path != PurePosixPath(RUNTIME_ROOT)
        and PurePosixPath(RUNTIME_ROOT) not in path.parents
    ):
        raise fail(
            "invalid_input",
            f"Runtime destination must be under {RUNTIME_ROOT}.",
            destination=value,
        )
    if ".." in path.parts:
        raise fail("invalid_input", "Runtime destination cannot contain '..'.")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(UPLOAD_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _code(operation: str, **payload: Any) -> str:
    """Build a small, data-safe runtime script; values enter only as JSON literals."""
    data = json.dumps(payload)
    return (
        "import base64, hashlib, json, os\n"
        f"_p = json.loads({json.dumps(data)})\n"
        f"_op = {operation!r}\n"
        f"_root = os.path.realpath({RUNTIME_ROOT!r})\n"
        "_target = os.path.realpath(_p['path'])\n"
        "if os.path.commonpath([_root, _target]) != _root:\n"
        " print(json.dumps({'error': {'kind': 'invalid_input', 'message': 'Runtime path escapes /content.'}}))\n"
        "elif _op == 'init':\n"
        " os.makedirs(os.path.dirname(_p['path']), exist_ok=True); open(_p['path'], 'wb').close()\n"
        "elif _op == 'append':\n"
        " with open(_p['path'], 'ab') as _f: _f.write(base64.b64decode(_p['chunk']))\n"
        "elif _op == 'verify':\n"
        " with open(_p['path'], 'rb') as _f: _b = _f.read()\n"
        " print(json.dumps({'size': len(_b), 'sha256': hashlib.sha256(_b).hexdigest()}))\n"
        "elif _op == 'remove':\n"
        " try: os.remove(_p['path'])\n"
        " except FileNotFoundError: pass\n"
        "elif _op == 'list':\n"
        " _root = _p['path']; print(json.dumps({'files': [{'path': os.path.join(_r, _n), 'size': os.path.getsize(os.path.join(_r, _n))} for _r, _, _ns in os.walk(_root) for _n in _ns]}))\n"
    )


def _payload(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        if "size" in result or "files" in result or "error" in result:
            return result
        for value in result.values():
            found = _payload(value)
            if found:
                return found
    if isinstance(result, list):
        for value in result:
            found = _payload(value)
            if found:
                return found
    if isinstance(result, str):
        try:
            return _payload(json.loads(result))
        except json.JSONDecodeError:
            return {}
    return {}


class UploadManager:
    """In-memory progress/cancellation state for transfers in this server process."""

    def __init__(self) -> None:
        self._uploads: dict[str, UploadStatus] = {}
        self._destinations: set[tuple[str, str]] = set()

    def status(self, upload_id: str) -> UploadStatus:
        try:
            return self._uploads[upload_id]
        except KeyError:
            raise fail("invalid_input", f"Unknown upload_id '{upload_id}'.") from None

    def cancel(self, upload_id: str) -> UploadStatus:
        status = self.status(upload_id)
        if status.state == "uploading":
            status.state = "cancelled"
        return status

    async def upload_file(
        self,
        session: NotebookSession,
        source: str,
        destination: str | None = None,
        upload_id: str | None = None,
    ) -> UploadStatus:
        host = _host_path(source)
        if not host.is_file():
            raise fail(
                "invalid_input", "Upload source must be a regular file.", path=str(host)
            )
        runtime = _runtime_path(destination or host.name)
        if upload_id is not None and not upload_id.strip():
            raise fail("invalid_input", "upload_id cannot be empty.")
        if upload_id is not None and upload_id in self._uploads:
            raise fail("invalid_input", f"upload_id '{upload_id}' is already in use.")
        try:
            size = host.stat().st_size
            digest = _sha256(host)
        except OSError:
            raise fail(
                "invalid_input", "Upload source cannot be read.", path=str(host)
            ) from None
        status = UploadStatus(
            upload_id=upload_id or uuid4().hex,
            notebook_id=session.notebook_id,
            source=str(host),
            destination=str(runtime),
            state="uploading",
            bytes_sent=0,
            size=size,
            sha256=digest,
        )
        self._uploads[status.upload_id] = status
        destination_key = (session.notebook_id, str(runtime))
        if destination_key in self._destinations:
            status.state = "failed"
            status.error = "Another upload already owns this runtime destination."
            raise fail(
                "invalid_input",
                "Another upload is already writing to this runtime destination.",
                notebook_id=session.notebook_id,
                destination=str(runtime),
            )
        self._destinations.add(destination_key)
        try:
            await self._run(session, "init", path=str(runtime))
            with host.open("rb") as stream:
                while chunk := stream.read(UPLOAD_CHUNK_SIZE):
                    if status.state == "cancelled":
                        raise fail("invalid_input", "Upload was cancelled.")
                    await self._run(
                        session,
                        "append",
                        path=str(runtime),
                        chunk=base64.b64encode(chunk).decode(),
                    )
                    status.bytes_sent += len(chunk)
            actual = _payload(await self._run(session, "verify", path=str(runtime)))
            if status.state == "cancelled":
                raise fail("invalid_input", "Upload was cancelled.")
            if actual.get("size") != status.size or actual.get("sha256") != digest:
                raise fail("protocol_error", "Runtime file verification failed.")
            status.state = "complete"
            return status
        except Exception as exc:
            cancelled = status.state == "cancelled"
            status.state = "cancelled" if cancelled else "failed"
            status.error = "Upload cancelled." if cancelled else "Upload failed."
            if isinstance(exc, _UnsafeRuntimePath):
                raise
            try:
                await self._run(session, "remove", path=str(runtime))
            except Exception:
                status.error = (
                    "Upload failed and cleanup could not be confirmed; "
                    "remove the incomplete runtime file manually."
                )
                raise fail(
                    "protocol_error",
                    "Upload failed and cleanup could not be confirmed. Remove the "
                    "incomplete runtime file manually.",
                    notebook_id=session.notebook_id,
                    destination=str(runtime),
                ) from None
            if isinstance(exc, ToolFailed):
                raise
            raise fail(
                "protocol_error",
                "Upload failed; the incomplete runtime file was removed.",
            ) from None
        finally:
            self._destinations.discard(destination_key)

    async def _run(
        self, session: NotebookSession, operation: str, **payload: Any
    ) -> dict[str, Any]:
        result = _payload(await session.run_code(_code(operation, **payload)))
        error = result.get("error")
        if isinstance(error, dict) and error.get("kind") == "invalid_input":
            failure = fail(
                "invalid_input",
                str(error.get("message") or "Runtime path is not allowed."),
                path=payload.get("path"),
            )
            raise _UnsafeRuntimePath(failure.error)
        return result

    async def upload_directory(
        self, session: NotebookSession, source: str, destination: str | None = None
    ) -> list[UploadStatus]:
        host = _host_path(source)
        if not host.is_dir():
            raise fail(
                "invalid_input", "Upload source must be a directory.", path=str(host)
            )
        root = _runtime_path(destination or host.name)
        return [
            await self.upload_file(
                session, str(path), str(root / path.relative_to(host).as_posix())
            )
            for path in sorted(host.rglob("*"))
            if path.is_file()
        ]

    async def list_runtime_files(
        self, session: NotebookSession, path: str = RUNTIME_ROOT
    ) -> list[dict[str, Any]]:
        runtime = _runtime_path(path)
        payload = await self._run(session, "list", path=str(runtime))
        files = payload.get("files")
        if not isinstance(files, list):
            raise fail(
                "protocol_error", "Runtime file listing returned an invalid response."
            )
        return files
