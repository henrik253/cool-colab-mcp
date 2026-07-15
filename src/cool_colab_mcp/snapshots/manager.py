"""Valid ``.ipynb`` persistence for notebook snapshots (plan.md §5)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from cool_colab_mcp.constants import (
    IPYNB_FORMAT,
    IPYNB_MINOR_FORMAT,
    NOTEBOOK_SUFFIX,
    SNAPSHOT_DIR_NAME,
    SNAPSHOT_TIMESTAMP_FORMAT,
)
from cool_colab_mcp.errors import fail
from cool_colab_mcp.storage import base_dir, save_json


class RecoveryMetadata(BaseModel):
    """Portable instructions and paths needed after the runtime itself disappears."""

    model_config = ConfigDict(extra="forbid")

    environment_setup_instructions: list[str] = Field(default_factory=list)
    git_repository: str | None = None
    git_commit: str | None = None
    checkpoint_paths: list[str] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)


def _snapshot_dir(notebook_id: str) -> Path:
    return base_dir() / SNAPSHOT_DIR_NAME / quote(notebook_id, safe="")


def _validate_snapshot_id(snapshot_id: str) -> str:
    if not snapshot_id or Path(snapshot_id).name != snapshot_id:
        raise fail("invalid_input", "snapshot_id must be a snapshot filename.")
    return snapshot_id.removesuffix(NOTEBOOK_SUFFIX)


def _source(cell: dict[str, Any]) -> str | list[str]:
    source = cell.get("source", cell.get("content", ""))
    if isinstance(source, str) or (
        isinstance(source, list) and all(isinstance(line, str) for line in source)
    ):
        return source
    raise fail("protocol_error", "get_cells returned a cell with invalid source.")


def _validate_document(document: Any, message: str) -> dict[str, Any]:
    """Strict nbformat-v4 subset validation for the fields this project persists."""
    if (
        not isinstance(document, dict)
        or document.get("nbformat") != IPYNB_FORMAT
        or not isinstance(document.get("nbformat_minor"), int)
        or not isinstance(document.get("metadata"), dict)
        or not isinstance(document.get("cells"), list)
    ):
        raise fail("protocol_error", message)
    for cell in document["cells"]:
        if (
            not isinstance(cell, dict)
            or cell.get("cell_type") not in {"code", "markdown"}
            or not isinstance(cell.get("metadata"), dict)
        ):
            raise fail("protocol_error", message)
        _source(cell)
        if "id" in cell and not isinstance(cell["id"], str):
            raise fail("protocol_error", message)
        if cell["cell_type"] == "code":
            count = cell.get("execution_count")
            outputs = cell.get("outputs")
            if (count is not None and not isinstance(count, int)) or not isinstance(
                outputs, list
            ):
                raise fail("protocol_error", message)
            if not all(_valid_output(output) for output in outputs):
                raise fail("protocol_error", message)
    try:
        json.dumps(document, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise fail("protocol_error", message) from exc
    return document


def load_notebook(path: Path) -> dict[str, Any]:
    """Read and validate one nbformat-v4 notebook from disk."""
    try:
        document = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise fail("protocol_error", f"Notebook '{path}' cannot be read.") from exc
    return _validate_document(document, f"Notebook '{path}' is not valid.")


def write_notebook(path: Path, document: dict[str, Any]) -> None:
    """Validate and atomically write one nbformat-v4 notebook."""
    save_json(path, _validate_document(document, "Notebook is invalid."))


def _valid_output(output: Any) -> bool:
    if not isinstance(output, dict):
        return False
    kind = output.get("output_type")
    if kind == "stream":
        text = output.get("text")
        return isinstance(output.get("name"), str) and (
            isinstance(text, str)
            or (isinstance(text, list) and all(isinstance(line, str) for line in text))
        )
    if kind in {"display_data", "update_display_data"}:
        return isinstance(output.get("data"), dict) and isinstance(
            output.get("metadata"), dict
        )
    if kind == "execute_result":
        count = output.get("execution_count")
        return (
            isinstance(output.get("data"), dict)
            and isinstance(output.get("metadata"), dict)
            and (count is None or isinstance(count, int))
        )
    if kind == "error":
        return (
            isinstance(output.get("ename"), str)
            and isinstance(output.get("evalue"), str)
            and isinstance(output.get("traceback"), list)
            and all(isinstance(line, str) for line in output["traceback"])
        )
    return False


def notebook_document(
    cells: Any, recovery: RecoveryMetadata | None = None
) -> dict[str, Any]:
    """Convert the frontend cell payload into nbformat v4 JSON."""
    if isinstance(cells, dict):
        cells = cells.get("cells")
    if not isinstance(cells, list) or not all(isinstance(cell, dict) for cell in cells):
        raise fail(
            "protocol_error",
            "get_cells returned an unexpected payload; the Colab frontend may have changed.",
        )
    converted = []
    for cell in cells:
        kind = cell.get("cell_type", cell.get("type", "code"))
        if kind not in {"code", "text", "markdown"}:
            raise fail("protocol_error", "get_cells returned an unknown cell type.")
        kind = "markdown" if kind in {"text", "markdown"} else "code"
        metadata = cell.get("metadata", {})
        if not isinstance(metadata, dict):
            raise fail("protocol_error", "get_cells returned invalid cell metadata.")
        item: dict[str, Any] = {
            "cell_type": kind,
            "metadata": metadata,
            "source": _source(cell),
        }
        cell_id = cell.get("id", cell.get("cellId"))
        if isinstance(cell_id, str):
            item["id"] = cell_id
        if kind == "code":
            item["execution_count"] = cell.get("execution_count")
            outputs = cell.get("outputs", [])
            if not isinstance(outputs, list):
                raise fail("protocol_error", "get_cells returned invalid cell outputs.")
            item["outputs"] = outputs
        converted.append(item)
    metadata: dict[str, Any] = {}
    if recovery is not None:
        metadata["cool_colab_mcp"] = {
            "recovery": recovery.model_dump(exclude_none=True)
        }
    return _validate_document(
        {
            "cells": converted,
            "metadata": metadata,
            "nbformat": IPYNB_FORMAT,
            "nbformat_minor": IPYNB_MINOR_FORMAT,
        },
        "get_cells could not be converted to a valid notebook.",
    )


class SnapshotManager:
    def create(self, notebook_id: str, document: dict[str, Any]) -> dict[str, Any]:
        snapshot_id = datetime.now(UTC).strftime(SNAPSHOT_TIMESTAMP_FORMAT)
        path = _snapshot_dir(notebook_id) / f"{snapshot_id}{NOTEBOOK_SUFFIX}"
        try:
            save_json(path, _validate_document(document, "Notebook is invalid."))
            return self._info(path)
        except OSError as exc:
            raise fail("protocol_error", "Snapshot storage is not writable.") from exc

    def list(self, notebook_id: str) -> list[dict[str, Any]]:
        directory = _snapshot_dir(notebook_id)
        try:
            if not directory.exists():
                return []
            return [
                self._info(path)
                for path in sorted(directory.glob(f"*{NOTEBOOK_SUFFIX}"))
            ]
        except OSError as exc:
            raise fail("protocol_error", "Snapshot storage cannot be read.") from exc

    def load(self, notebook_id: str, snapshot_id: str) -> dict[str, Any]:
        snapshot_id = _validate_snapshot_id(snapshot_id)
        path = _snapshot_dir(notebook_id) / f"{snapshot_id}{NOTEBOOK_SUFFIX}"
        try:
            exists = path.is_file()
        except OSError as exc:
            raise fail("protocol_error", "Snapshot storage cannot be read.") from exc
        if not exists:
            raise fail(
                "invalid_input",
                f"Snapshot '{snapshot_id}' does not exist for notebook '{notebook_id}'.",
                notebook_id=notebook_id,
                snapshot_id=snapshot_id,
            )
        return load_notebook(path)

    def export(self, document: dict[str, Any], destination: str) -> Path:
        path = Path(destination).expanduser()
        if path.suffix != NOTEBOOK_SUFFIX:
            raise fail("invalid_input", f"destination must end with {NOTEBOOK_SUFFIX}.")
        try:
            write_notebook(path, document)
        except OSError as exc:
            raise fail("invalid_input", f"Cannot write notebook to '{path}'.") from exc
        return path

    @staticmethod
    def _info(path: Path) -> dict[str, Any]:
        return {
            "snapshot_id": path.stem,
            "path": str(path),
            "created_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
        }
