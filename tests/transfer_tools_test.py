import hashlib
import json
import asyncio
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastmcp import Client

from cool_colab_mcp.constants import UPLOAD_DIRS_ENV
from cool_colab_mcp.server import build_server
from cool_colab_mcp.sessions.manager import SessionManager


TRANSFER_TOOLS = {
    "upload_file",
    "upload_directory",
    "get_upload_status",
    "cancel_upload",
    "list_runtime_files",
}


def selected(code: str, operation: str) -> bool:
    return f"_op = {operation!r}" in code


@pytest_asyncio.fixture
async def manager():
    value = SessionManager()
    yield value
    await value.aclose()


@pytest.fixture
def server(manager):
    return build_server(manager)


class TestToolSurface:
    @pytest.mark.asyncio
    async def test_transfer_tools_are_pre_registered(self, server):
        async with Client(server) as client:
            names = {tool.name for tool in await client.list_tools()}
        assert TRANSFER_TOOLS <= names

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "name,args",
        [
            ("upload_file", {"source": "x"}),
            ("upload_directory", {"source": "x"}),
            ("list_runtime_files", {}),
        ],
    )
    async def test_session_tools_return_not_connected(self, server, name, args):
        async with Client(server) as client:
            result = await client.call_tool(name, args)
        assert result.structured_content["error"]["kind"] == "not_connected"


class TestUploadFileTool:
    @pytest.mark.asyncio
    async def test_uploads_and_returns_status(
        self, server, manager, tmp_path, monkeypatch
    ):
        monkeypatch.setenv(UPLOAD_DIRS_ENV, str(tmp_path))
        data = b"hello"
        source = tmp_path / "hello.txt"
        source.write_bytes(data)
        notebook = await manager.get_or_create()
        notebook.run_code = AsyncMock(
            side_effect=[
                {},
                {},
                {
                    "text": json.dumps(
                        {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                    )
                },
            ]
        )

        async with Client(server) as client:
            result = await client.call_tool("upload_file", {"source": str(source)})

        assert result.structured_content["state"] == "complete"
        assert result.structured_content["destination"] == "/content/hello.txt"

    @pytest.mark.asyncio
    async def test_bad_host_path_returns_structured_error(
        self, server, manager, monkeypatch, tmp_path
    ):
        monkeypatch.setenv(UPLOAD_DIRS_ENV, str(tmp_path / "allowed"))
        await manager.get_or_create()
        async with Client(server) as client:
            result = await client.call_tool(
                "upload_file", {"source": str(tmp_path / "outside")}
            )
        assert result.structured_content["error"]["kind"] == "invalid_input"

    @pytest.mark.asyncio
    async def test_failure_is_structured(self, server, manager, tmp_path, monkeypatch):
        monkeypatch.setenv(UPLOAD_DIRS_ENV, str(tmp_path))
        source = tmp_path / "file"
        source.write_bytes(b"x")
        notebook = await manager.get_or_create()
        notebook.run_code = AsyncMock(
            side_effect=[{}, {}, {"size": 0, "sha256": "bad"}, {}]
        )
        async with Client(server) as client:
            result = await client.call_tool("upload_file", {"source": str(source)})
        assert result.structured_content["error"]["kind"] == "protocol_error"

    @pytest.mark.asyncio
    async def test_routes_to_named_notebook(
        self, server, manager, tmp_path, monkeypatch
    ):
        monkeypatch.setenv(UPLOAD_DIRS_ENV, str(tmp_path))
        data = b"x"
        source = tmp_path / "file"
        source.write_bytes(data)
        default = await manager.get_or_create()
        default.run_code = AsyncMock()
        named = await manager.get_or_create("named")
        named.run_code = AsyncMock(
            side_effect=[
                {},
                {},
                {"size": 1, "sha256": hashlib.sha256(data).hexdigest()},
            ]
        )
        async with Client(server) as client:
            result = await client.call_tool(
                "upload_file", {"source": str(source), "notebook_id": "named"}
            )
        assert result.structured_content["notebook_id"] == "named"
        default.run_code.assert_not_awaited()


class TestUploadDirectoryTool:
    @pytest.mark.asyncio
    async def test_happy_path(self, server, manager, tmp_path, monkeypatch):
        monkeypatch.setenv(UPLOAD_DIRS_ENV, str(tmp_path))
        directory = tmp_path / "data"
        directory.mkdir()
        (directory / "a").write_bytes(b"a")
        notebook = await manager.get_or_create()
        notebook.run_code = AsyncMock(
            side_effect=[
                {},
                {},
                {"size": 1, "sha256": hashlib.sha256(b"a").hexdigest()},
            ]
        )
        async with Client(server) as client:
            result = await client.call_tool(
                "upload_directory", {"source": str(directory)}
            )
        assert result.structured_content["uploads"][0]["state"] == "complete"

    @pytest.mark.asyncio
    async def test_file_source_is_invalid(self, server, manager, tmp_path, monkeypatch):
        monkeypatch.setenv(UPLOAD_DIRS_ENV, str(tmp_path))
        source = tmp_path / "file"
        source.write_text("x")
        await manager.get_or_create()
        async with Client(server) as client:
            result = await client.call_tool("upload_directory", {"source": str(source)})
        assert result.structured_content["error"]["kind"] == "invalid_input"

    @pytest.mark.asyncio
    async def test_child_failure_is_structured_and_routes(
        self, server, manager, tmp_path, monkeypatch
    ):
        monkeypatch.setenv(UPLOAD_DIRS_ENV, str(tmp_path))
        directory = tmp_path / "data"
        directory.mkdir()
        (directory / "a").write_bytes(b"a")
        named = await manager.get_or_create("named")
        named.run_code = AsyncMock(side_effect=[RuntimeError("failed"), {}])
        async with Client(server) as client:
            result = await client.call_tool(
                "upload_directory", {"source": str(directory), "notebook_id": "named"}
            )
        assert result.structured_content["error"]["kind"] == "protocol_error"
        named.run_code.assert_awaited()


class TestStatusAndCancelTools:
    @pytest.mark.asyncio
    async def test_active_status_and_cancel_happy_path(
        self, server, manager, tmp_path, monkeypatch
    ):
        monkeypatch.setenv(UPLOAD_DIRS_ENV, str(tmp_path))
        source = tmp_path / "file"
        source.write_bytes(b"x")
        notebook = await manager.get_or_create()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def run(code):
            if selected(code, "init"):
                entered.set()
                await release.wait()
            return {}

        notebook.run_code = AsyncMock(side_effect=run)
        async with Client(server) as uploader, Client(server) as controller:
            task = asyncio.create_task(
                uploader.call_tool(
                    "upload_file", {"source": str(source), "upload_id": "active"}
                )
            )
            await entered.wait()
            status = await controller.call_tool(
                "get_upload_status", {"upload_id": "active"}
            )
            cancelled = await controller.call_tool(
                "cancel_upload", {"upload_id": "active"}
            )
            release.set()
            await task
        assert status.structured_content["state"] == "uploading"
        assert cancelled.structured_content["state"] == "cancelled"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", ["get_upload_status", "cancel_upload"])
    async def test_unknown_id_is_invalid(self, server, name):
        async with Client(server) as client:
            result = await client.call_tool(name, {"upload_id": "missing"})
        assert result.structured_content["error"]["kind"] == "invalid_input"


class TestListRuntimeFilesTool:
    @pytest.mark.asyncio
    async def test_happy_path_routes_to_named_notebook(self, server, manager):
        default = await manager.get_or_create()
        default.run_code = AsyncMock()
        named = await manager.get_or_create("named")
        files = [{"path": "/content/a", "size": 1}]
        named.run_code = AsyncMock(return_value={"files": files})
        async with Client(server) as client:
            result = await client.call_tool(
                "list_runtime_files", {"notebook_id": "named"}
            )
        assert result.structured_content == {"files": files}
        default.run_code.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_path_outside_content_is_invalid(self, server, manager):
        await manager.get_or_create()
        async with Client(server) as client:
            result = await client.call_tool("list_runtime_files", {"path": "/tmp"})
        assert result.structured_content["error"]["kind"] == "invalid_input"

    @pytest.mark.asyncio
    async def test_bad_runtime_response_is_structured(self, server, manager):
        notebook = await manager.get_or_create()
        notebook.run_code = AsyncMock(return_value={})
        async with Client(server) as client:
            result = await client.call_tool("list_runtime_files", {})
        assert result.structured_content["error"]["kind"] == "protocol_error"
