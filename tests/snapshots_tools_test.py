"""Snapshot MCP tool tests."""

import json

import pytest
import pytest_asyncio
from conftest import fake_raw_result, mock_proxy_client
from fastmcp import Client

from cool_colab_mcp.server import build_server
from cool_colab_mcp.sessions.manager import SessionManager


CELLS = {
    "cells": [
        {"cellId": "c1", "type": "code", "content": "x = 1", "outputs": []},
        {"cellId": "c2", "type": "text", "content": "# Notes"},
    ]
}


@pytest_asyncio.fixture
async def manager():
    manager = SessionManager()
    yield manager
    await manager.aclose()


@pytest.fixture
def server(manager):
    return build_server(manager)


async def connect(manager, results):
    session = await manager.get_or_create("training")
    session.proxy_client = mock_proxy_client(results)
    return session


@pytest.mark.asyncio
async def test_create_snapshot_writes_valid_ipynb(server, manager):
    await connect(manager, [fake_raw_result(CELLS)])
    async with Client(server) as client:
        result = await client.call_tool("create_snapshot", {"notebook_id": "training"})
    document = json.loads(open(result.structured_content["snapshot"]["path"]).read())
    assert document["nbformat"] == 4
    assert [cell["cell_type"] for cell in document["cells"]] == ["code", "markdown"]


@pytest.mark.asyncio
async def test_create_snapshot_stores_recovery_metadata(server, manager):
    await connect(manager, [fake_raw_result(CELLS)])
    async with Client(server) as client:
        result = await client.call_tool(
            "create_snapshot",
            {
                "notebook_id": "training",
                "environment_setup_instructions": ["pip install example"],
                "git_repository": "https://example.test/repo.git",
                "git_commit": "abc123",
                "checkpoint_paths": ["/content/model.ckpt"],
                "artifact_paths": ["/content/output.csv"],
            },
        )
    document = json.loads(open(result.structured_content["snapshot"]["path"]).read())
    assert document["metadata"]["cool_colab_mcp"]["recovery"]["git_commit"] == "abc123"


@pytest.mark.asyncio
async def test_create_snapshot_disconnected_is_structured(server, manager):
    await manager.get_or_create("training")
    async with Client(server) as client:
        result = await client.call_tool("create_snapshot", {"notebook_id": "training"})
    assert result.structured_content["error"]["kind"] == "not_connected"


@pytest.mark.asyncio
async def test_create_snapshot_unknown_notebook_is_structured(server):
    async with Client(server) as client:
        result = await client.call_tool("create_snapshot", {"notebook_id": "missing"})
    assert result.structured_content["error"]["kind"] == "unknown_notebook"


@pytest.mark.asyncio
async def test_list_snapshots_survives_server_restart(manager):
    first = build_server(manager)
    await connect(manager, [fake_raw_result(CELLS)])
    async with Client(first) as client:
        await client.call_tool("create_snapshot", {"notebook_id": "training"})
    second = build_server(manager)
    async with Client(second) as client:
        result = await client.call_tool("list_snapshots", {"notebook_id": "training"})
    assert len(result.structured_content["snapshots"]) == 1


@pytest.mark.asyncio
async def test_list_snapshots_rejects_empty_notebook_id(server):
    async with Client(server) as client:
        result = await client.call_tool("list_snapshots", {"notebook_id": ""})
    assert result.structured_content["error"]["kind"] == "invalid_input"


@pytest.mark.asyncio
async def test_list_snapshots_filesystem_failure_is_structured(server, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("sentinel must not leak")

    monkeypatch.setattr("cool_colab_mcp.snapshots.manager.Path.exists", denied)
    async with Client(server) as client:
        result = await client.call_tool("list_snapshots", {"notebook_id": "training"})
    assert result.structured_content["error"]["kind"] == "protocol_error"
    assert "sentinel" not in str(result.structured_content)


@pytest.mark.asyncio
async def test_restore_snapshot_replaces_cells_in_order(server, manager):
    session = await connect(
        manager,
        [
            fake_raw_result(CELLS),
            fake_raw_result({"cells": [{"cellId": "old"}]}),
            fake_raw_result(),
            fake_raw_result(),
            fake_raw_result(),
        ],
    )
    async with Client(server) as client:
        made = await client.call_tool("create_snapshot", {"notebook_id": "training"})
        snapshot_id = made.structured_content["snapshot"]["snapshot_id"]
        result = await client.call_tool(
            "restore_snapshot", {"notebook_id": "training", "snapshot_id": snapshot_id}
        )
    assert result.structured_content["restored"] == snapshot_id
    assert session.proxy_client.call_tool.call_args_list[2].args == (
        "delete_cell",
        {"cellId": "old"},
    )
    assert session.proxy_client.call_tool.call_args_list[3].args == (
        "add_code_cell",
        {"code": "x = 1", "cellIndex": 0, "language": "python"},
    )
    assert session.proxy_client.call_tool.call_args_list[4].args == (
        "add_text_cell",
        {"content": "# Notes", "cellIndex": 1},
    )


@pytest.mark.asyncio
async def test_restore_unknown_snapshot_is_structured(server, manager):
    await connect(manager, [])
    async with Client(server) as client:
        result = await client.call_tool(
            "restore_snapshot", {"notebook_id": "training", "snapshot_id": "missing"}
        )
    assert result.structured_content["error"]["kind"] == "invalid_input"


@pytest.mark.asyncio
async def test_restore_disconnected_is_structured(server, manager):
    session = await manager.get_or_create("training")
    from cool_colab_mcp.snapshots.manager import SnapshotManager, notebook_document

    made = SnapshotManager().create("training", notebook_document(CELLS))
    async with Client(server) as client:
        result = await client.call_tool(
            "restore_snapshot",
            {"notebook_id": "training", "snapshot_id": made["snapshot_id"]},
        )
    assert session.is_connected() is False
    assert result.structured_content["error"]["kind"] == "not_connected"


@pytest.mark.asyncio
async def test_restore_unknown_notebook_is_structured(server):
    async with Client(server) as client:
        result = await client.call_tool(
            "restore_snapshot", {"notebook_id": "missing", "snapshot_id": "anything"}
        )
    assert result.structured_content["error"]["kind"] == "unknown_notebook"


@pytest.mark.asyncio
async def test_export_notebook_writes_current_cells(server, manager, tmp_path):
    await connect(manager, [fake_raw_result(CELLS)])
    destination = tmp_path / "export.ipynb"
    async with Client(server) as client:
        result = await client.call_tool(
            "export_notebook",
            {"notebook_id": "training", "destination": str(destination)},
        )
    assert result.structured_content["path"] == str(destination)
    assert json.loads(destination.read_text())["cells"][1]["source"] == "# Notes"


@pytest.mark.asyncio
async def test_export_merges_outputs_returned_by_run_cell(server, manager, tmp_path):
    outputs = [{"output_type": "stream", "name": "stdout", "text": ["saved\n"]}]
    await connect(
        manager,
        [fake_raw_result({"outputs": outputs}), fake_raw_result(CELLS)],
    )
    destination = tmp_path / "export.ipynb"
    async with Client(server) as client:
        await client.call_tool(
            "run_code_cell", {"notebook_id": "training", "cellId": "c1"}
        )
        await client.call_tool(
            "export_notebook",
            {"notebook_id": "training", "destination": str(destination)},
        )
    assert json.loads(destination.read_text())["cells"][0]["outputs"] == outputs


@pytest.mark.asyncio
async def test_export_bad_destination_is_structured(server, manager, tmp_path):
    await connect(manager, [fake_raw_result(CELLS)])
    async with Client(server) as client:
        result = await client.call_tool(
            "export_notebook",
            {"notebook_id": "training", "destination": str(tmp_path / "bad.json")},
        )
    assert result.structured_content["error"]["kind"] == "invalid_input"


@pytest.mark.asyncio
async def test_export_disconnected_is_structured(server, manager, tmp_path):
    await manager.get_or_create("training")
    async with Client(server) as client:
        result = await client.call_tool(
            "export_notebook",
            {"notebook_id": "training", "destination": str(tmp_path / "out.ipynb")},
        )
    assert result.structured_content["error"]["kind"] == "not_connected"


@pytest.mark.asyncio
async def test_export_unknown_notebook_is_structured(server, tmp_path):
    async with Client(server) as client:
        result = await client.call_tool(
            "export_notebook",
            {"notebook_id": "missing", "destination": str(tmp_path / "out.ipynb")},
        )
    assert result.structured_content["error"]["kind"] == "unknown_notebook"


@pytest.mark.asyncio
async def test_export_filesystem_failure_is_structured(
    server, manager, tmp_path, monkeypatch
):
    await connect(manager, [fake_raw_result(CELLS)])

    def denied(*args, **kwargs):
        raise PermissionError("sentinel must not leak")

    monkeypatch.setattr("cool_colab_mcp.snapshots.manager.save_json", denied)
    async with Client(server) as client:
        result = await client.call_tool(
            "export_notebook",
            {"notebook_id": "training", "destination": str(tmp_path / "out.ipynb")},
        )
    assert result.structured_content["error"]["kind"] == "invalid_input"
    assert "sentinel" not in str(result.structured_content)
