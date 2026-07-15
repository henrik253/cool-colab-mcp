"""Snapshot persistence tests."""

import json

import pytest

from cool_colab_mcp.errors import ToolFailed
from cool_colab_mcp.snapshots.manager import (
    RecoveryMetadata,
    SnapshotManager,
    notebook_document,
)


CELLS = {
    "cells": [
        {
            "cellId": "code-1",
            "type": "code",
            "content": "print('hi')",
            "metadata": {"tags": ["setup"]},
            "outputs": [{"output_type": "stream", "name": "stdout", "text": "hi\n"}],
        },
        {"id": "text-1", "type": "text", "content": "# Heading"},
    ]
}


def test_notebook_document_preserves_cells_metadata_and_outputs():
    document = notebook_document(CELLS)
    assert document["nbformat"] == 4
    assert [cell["cell_type"] for cell in document["cells"]] == ["code", "markdown"]
    assert document["cells"][0]["metadata"] == {"tags": ["setup"]}
    assert document["cells"][0]["outputs"][0]["text"] == "hi\n"


def test_notebook_document_stores_recovery_metadata():
    recovery = RecoveryMetadata(
        environment_setup_instructions=["uv sync"],
        git_repository="https://example.test/repo.git",
        git_commit="abc123",
        checkpoint_paths=["/content/model.ckpt"],
        artifact_paths=["/content/results.json"],
    )
    document = notebook_document(CELLS, recovery)
    assert document["metadata"]["cool_colab_mcp"]["recovery"] == {
        "environment_setup_instructions": ["uv sync"],
        "git_repository": "https://example.test/repo.git",
        "git_commit": "abc123",
        "checkpoint_paths": ["/content/model.ckpt"],
        "artifact_paths": ["/content/results.json"],
    }


def test_unexpected_cell_payload_is_protocol_error():
    with pytest.raises(ToolFailed) as failure:
        notebook_document({"changed": []})
    assert failure.value.error.kind == "protocol_error"


@pytest.mark.parametrize(
    "cell",
    [
        {"type": "widget", "content": "x"},
        {"type": "code", "content": 7},
        {"type": "code", "content": "x", "metadata": []},
        {"type": "code", "content": "x", "outputs": {}},
        {"type": "code", "content": "x", "outputs": [{"text": "missing type"}]},
    ],
)
def test_malformed_frontend_cells_are_rejected(cell):
    with pytest.raises(ToolFailed) as failure:
        notebook_document({"cells": [cell]})
    assert failure.value.error.kind == "protocol_error"


def test_create_list_load_roundtrip_survives_reinstantiation():
    document = notebook_document(CELLS)
    created = SnapshotManager().create("training", document)
    listed = SnapshotManager().list("training")
    assert [item["snapshot_id"] for item in listed] == [created["snapshot_id"]]
    assert SnapshotManager().load("training", created["snapshot_id"]) == document
    json.loads(open(created["path"]).read())


def test_unknown_snapshot_is_structured_invalid_input():
    with pytest.raises(ToolFailed) as failure:
        SnapshotManager().load("training", "missing")
    assert failure.value.error.kind == "invalid_input"


def test_snapshot_id_cannot_escape_notebook_directory():
    with pytest.raises(ToolFailed) as failure:
        SnapshotManager().load("training", "../secret")
    assert failure.value.error.kind == "invalid_input"


def test_notebook_id_cannot_escape_snapshot_directory(isolated_home):
    created = SnapshotManager().create("../outside", notebook_document(CELLS))
    assert str(isolated_home / "snapshots") in created["path"]
    assert not (isolated_home / "outside").exists()


def test_corrupt_snapshot_is_protocol_error(isolated_home):
    manager = SnapshotManager()
    created = manager.create("training", notebook_document(CELLS))
    open(created["path"], "w").write("{not json")
    with pytest.raises(ToolFailed) as failure:
        manager.load("training", created["snapshot_id"])
    assert failure.value.error.kind == "protocol_error"


def test_schema_invalid_snapshot_is_protocol_error():
    manager = SnapshotManager()
    created = manager.create("training", notebook_document(CELLS))
    open(created["path"], "w").write('{"cells": [], "nbformat": 3}')
    with pytest.raises(ToolFailed) as failure:
        manager.load("training", created["snapshot_id"])
    assert failure.value.error.kind == "protocol_error"


def test_create_filesystem_failure_is_structured(monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr("cool_colab_mcp.snapshots.manager.save_json", denied)
    with pytest.raises(ToolFailed) as failure:
        SnapshotManager().create("training", notebook_document(CELLS))
    assert failure.value.error.kind == "protocol_error"


def test_list_filesystem_failure_is_structured(monkeypatch):
    def denied(self):
        raise PermissionError("denied")

    monkeypatch.setattr("pathlib.Path.exists", denied)
    with pytest.raises(ToolFailed) as failure:
        SnapshotManager().list("training")
    assert failure.value.error.kind == "protocol_error"


def test_export_requires_ipynb_suffix(tmp_path):
    with pytest.raises(ToolFailed) as failure:
        SnapshotManager().export(
            notebook_document(CELLS), str(tmp_path / "notebook.json")
        )
    assert failure.value.error.kind == "invalid_input"


def test_export_writes_valid_notebook(tmp_path):
    path = SnapshotManager().export(
        notebook_document(CELLS), str(tmp_path / "notebook.ipynb")
    )
    assert json.loads(path.read_text())["nbformat"] == 4
