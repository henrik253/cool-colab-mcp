# Copyright 2026 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import webbrowser
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from conftest import fake_raw_result, mock_proxy_client
from fastmcp import Client

from cool_colab_mcp.constants import (
    COLAB,
    HOME_ENV,
    NOTEBOOK_DIRS_ENV,
    NOTEBOOK_URL_ENV,
    PROXY_PORT_PARAM,
    PROXY_TOKEN_PARAM,
    TAB_DEDUP_PARAM,
)
from cool_colab_mcp.registry.records import NotebookRecord, NotebookRegistry
from cool_colab_mcp.server import build_server
from cool_colab_mcp.sessions.manager import SessionManager
from cool_colab_mcp.sessions.session import NotebookSession

DRIVE_URL = f"{COLAB}/drive/file-id-1"
OTHER_URL = f"{COLAB}/drive/file-id-2"

REGISTRY_TOOLS = {
    "register_notebook",
    "list_notebooks",
    "remove_notebook",
    "get_notebook_status",
    "open_notebook",
    "close_notebook",
    "sync_notebook_to_colab",
    "sync_notebook_to_local",
}


@pytest.fixture(autouse=True)
def home_override(tmp_path, monkeypatch):
    monkeypatch.setenv(HOME_ENV, str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def mock_webbrowser(monkeypatch):
    mock_open = Mock()
    monkeypatch.setattr(webbrowser, "open_new", mock_open)
    return mock_open


@pytest.fixture(autouse=True)
def fast_timeout(monkeypatch):
    monkeypatch.setattr("cool_colab_mcp.server.UI_CONNECTION_TIMEOUT", 0.05)


@pytest_asyncio.fixture
async def manager():
    manager = SessionManager()
    yield manager
    await manager.aclose()


@pytest.fixture
def server(manager):
    return build_server(manager)


def registered(notebook_id="training", url=DRIVE_URL, **overrides) -> NotebookRecord:
    """Seed the shared persistent store with one record."""
    record = NotebookRecord(
        notebook_id=notebook_id, name="Training", url=url, **overrides
    )
    NotebookRegistry().register(record)
    return record


def local_notebook(tmp_path, monkeypatch):
    monkeypatch.setenv(NOTEBOOK_DIRS_ENV, str(tmp_path))
    path = tmp_path / "training.ipynb"
    path.write_text(
        json.dumps(
            {
                "cells": [
                    {
                        "cell_type": "code",
                        "metadata": {},
                        "source": "x = 1",
                        "execution_count": None,
                        "outputs": [],
                    }
                ],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        )
    )
    return path


class TestToolSurface:
    @pytest.mark.asyncio
    async def test_registry_tools_listed(self, server):
        async with Client(server) as client:
            tools = {tool.name for tool in await client.list_tools()}
        assert REGISTRY_TOOLS <= tools


class TestRegisterNotebook:
    @pytest.mark.asyncio
    async def test_registers_and_returns_record(self, server):
        async with Client(server) as client:
            result = await client.call_tool(
                "register_notebook",
                {
                    "notebook_id": "training",
                    "name": "Training",
                    "url": DRIVE_URL,
                    "preferred_runtime": "gpu",
                },
            )
        assert result.structured_content == {
            "notebook": {
                "notebook_id": "training",
                "name": "Training",
                "url": DRIVE_URL,
                "preferred_runtime": "gpu",
            }
        }
        assert NotebookRegistry().get("training").preferred_runtime == "gpu"

    @pytest.mark.asyncio
    async def test_reregistering_existing_id_updates(self, server):
        registered()
        async with Client(server) as client:
            await client.call_tool(
                "register_notebook",
                {"notebook_id": "training", "name": "Renamed", "url": OTHER_URL},
            )
            result = await client.call_tool("list_notebooks", {})
        assert result.structured_content == {
            "notebooks": [
                {"notebook_id": "training", "name": "Renamed", "url": OTHER_URL}
            ]
        }

    @pytest.mark.asyncio
    async def test_invalid_url_returns_invalid_input(self, server):
        async with Client(server) as client:
            result = await client.call_tool(
                "register_notebook",
                {"notebook_id": "x", "name": "X", "url": "https://evil.com/drive/x"},
            )
        assert result.structured_content["error"]["kind"] == "invalid_input"
        assert NotebookRegistry().list() == []

    @pytest.mark.asyncio
    async def test_empty_notebook_id_returns_invalid_input(self, server):
        async with Client(server) as client:
            result = await client.call_tool(
                "register_notebook",
                {"notebook_id": "", "name": "X", "url": DRIVE_URL},
            )
        assert result.structured_content["error"]["kind"] == "invalid_input"

    @pytest.mark.asyncio
    async def test_registers_allowed_local_notebook(
        self, server, tmp_path, monkeypatch
    ):
        path = local_notebook(tmp_path, monkeypatch)
        async with Client(server) as client:
            result = await client.call_tool(
                "register_notebook",
                {
                    "notebook_id": "training",
                    "name": "Training",
                    "local_path": str(path),
                },
            )
        assert result.structured_content["notebook"]["local_path"] == str(path)

    @pytest.mark.asyncio
    async def test_local_notebook_outside_allowlist_is_rejected(
        self, server, tmp_path, tmp_path_factory, monkeypatch
    ):
        monkeypatch.setenv(NOTEBOOK_DIRS_ENV, str(tmp_path))
        outside = tmp_path_factory.mktemp("outside") / "local.ipynb"
        outside.write_text('{"cells":[],"metadata":{},"nbformat":4,"nbformat_minor":5}')
        async with Client(server) as client:
            result = await client.call_tool(
                "register_notebook",
                {
                    "notebook_id": "training",
                    "name": "Training",
                    "local_path": str(outside),
                },
            )
        assert result.structured_content["error"]["kind"] == "invalid_input"


class TestLocalNotebookSync:
    @pytest.mark.asyncio
    async def test_open_local_notebook_restores_it_into_scratch_colab(
        self, server, manager, mock_webbrowser, tmp_path, monkeypatch
    ):
        path = local_notebook(tmp_path, monkeypatch)
        registered(url=None, local_path=str(path))
        monkeypatch.setenv(NOTEBOOK_URL_ENV, OTHER_URL)

        async def connect(self, timeout):
            self.proxy_client = mock_proxy_client(
                [
                    fake_raw_result({"cells": [{"cellId": "old"}]}),
                    fake_raw_result(),
                    fake_raw_result(),
                ]
            )
            return True

        monkeypatch.setattr(NotebookSession, "await_connection", connect)
        async with Client(server) as client:
            result = await client.call_tool(
                "open_notebook", {"notebook_id": "training"}
            )
        assert result.structured_content["synced"] is True
        assert result.structured_content["local_path"] == str(path)
        assert mock_webbrowser.call_args.args[0].startswith(
            "https://colab.research.google.com/notebooks/empty.ipynb?"
        )
        assert manager.get("training").proxy_client.call_tool.call_args_list[
            -1
        ].args == (
            "add_code_cell",
            {"code": "x = 1", "cellIndex": 0, "language": "python"},
        )

    @pytest.mark.asyncio
    async def test_sync_to_colab_replaces_cells(
        self, server, manager, tmp_path, monkeypatch
    ):
        path = local_notebook(tmp_path, monkeypatch)
        registered(url=None, local_path=str(path))
        session = await manager.get_or_create("training")
        session.proxy_client = mock_proxy_client(
            [
                fake_raw_result({"cells": [{"cellId": "old"}]}),
                fake_raw_result(),
                fake_raw_result(),
            ]
        )
        async with Client(server) as client:
            result = await client.call_tool(
                "sync_notebook_to_colab", {"notebook_id": "training"}
            )
        assert result.structured_content["direction"] == "to_colab"
        assert session.proxy_client.call_tool.call_args_list[-1].args == (
            "add_code_cell",
            {"code": "x = 1", "cellIndex": 0, "language": "python"},
        )

    @pytest.mark.asyncio
    async def test_sync_to_local_atomically_writes_current_cells(
        self, server, manager, tmp_path, monkeypatch
    ):
        path = local_notebook(tmp_path, monkeypatch)
        registered(url=None, local_path=str(path))
        session = await manager.get_or_create("training")
        session.proxy_client = mock_proxy_client(
            [
                fake_raw_result(
                    {
                        "cells": [
                            {
                                "cellId": "new",
                                "type": "text",
                                "content": "# Changed in Colab",
                            }
                        ]
                    }
                )
            ]
        )
        async with Client(server) as client:
            result = await client.call_tool(
                "sync_notebook_to_local", {"notebook_id": "training"}
            )
        assert result.structured_content["direction"] == "to_local"
        assert (
            json.loads(path.read_text())["cells"][0]["source"] == "# Changed in Colab"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "tool", ["sync_notebook_to_colab", "sync_notebook_to_local"]
    )
    async def test_remote_record_rejects_local_sync(self, server, tool):
        registered()
        async with Client(server) as client:
            result = await client.call_tool(tool, {"notebook_id": "training"})
        assert result.structured_content["error"]["kind"] == "invalid_input"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "tool", ["sync_notebook_to_colab", "sync_notebook_to_local"]
    )
    async def test_unknown_notebook_is_structured(self, server, tool):
        async with Client(server) as client:
            result = await client.call_tool(tool, {"notebook_id": "missing"})
        assert result.structured_content["error"]["kind"] == "unknown_notebook"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "tool", ["sync_notebook_to_colab", "sync_notebook_to_local"]
    )
    async def test_disconnected_local_notebook_is_structured(
        self, server, manager, tmp_path, monkeypatch, tool
    ):
        path = local_notebook(tmp_path, monkeypatch)
        registered(url=None, local_path=str(path))
        await manager.get_or_create("training")
        async with Client(server) as client:
            result = await client.call_tool(tool, {"notebook_id": "training"})
        assert result.structured_content["error"]["kind"] == "not_connected"

    @pytest.mark.asyncio
    async def test_malformed_local_file_fails_without_touching_colab(
        self, server, manager, tmp_path, monkeypatch
    ):
        path = local_notebook(tmp_path, monkeypatch)
        registered(url=None, local_path=str(path))
        session = await manager.get_or_create("training")
        session.proxy_client = mock_proxy_client([])
        path.write_text("{not json")
        async with Client(server) as client:
            result = await client.call_tool(
                "sync_notebook_to_colab", {"notebook_id": "training"}
            )
        assert result.structured_content["error"]["kind"] == "protocol_error"
        session.proxy_client.call_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_sync_to_local_preserves_original_file(
        self, server, manager, tmp_path, monkeypatch
    ):
        path = local_notebook(tmp_path, monkeypatch)
        original = path.read_text()
        registered(url=None, local_path=str(path))
        session = await manager.get_or_create("training")
        session.proxy_client = mock_proxy_client([fake_raw_result({"cells": []})])

        def denied(*args, **kwargs):
            raise PermissionError("sentinel")

        monkeypatch.setattr("cool_colab_mcp.snapshots.manager.save_json", denied)
        async with Client(server) as client:
            result = await client.call_tool(
                "sync_notebook_to_local", {"notebook_id": "training"}
            )
        assert result.structured_content["error"]["kind"] == "invalid_input"
        assert path.read_text() == original


class TestListNotebooks:
    @pytest.mark.asyncio
    async def test_empty_registry_lists_nothing(self, server):
        async with Client(server) as client:
            result = await client.call_tool("list_notebooks", {})
        assert result.structured_content == {"notebooks": []}

    @pytest.mark.asyncio
    async def test_lists_all_records(self, server):
        registered("a")
        registered("b", url=OTHER_URL, preferred_runtime="gpu")
        async with Client(server) as client:
            result = await client.call_tool("list_notebooks", {})
        notebooks = result.structured_content["notebooks"]
        assert {nb["notebook_id"] for nb in notebooks} == {"a", "b"}


class TestRemoveNotebook:
    @pytest.mark.asyncio
    async def test_removes_record(self, server):
        registered()
        async with Client(server) as client:
            result = await client.call_tool(
                "remove_notebook", {"notebook_id": "training"}
            )
        assert result.structured_content == {"removed": "training"}
        assert NotebookRegistry().list() == []

    @pytest.mark.asyncio
    async def test_unknown_id_returns_unknown_notebook(self, server):
        async with Client(server) as client:
            result = await client.call_tool(
                "remove_notebook", {"notebook_id": "missing"}
            )
        error = result.structured_content["error"]
        assert error["kind"] == "unknown_notebook"
        assert error["details"] == {"notebook_id": "missing"}


class TestGetNotebookStatus:
    @pytest.mark.asyncio
    async def test_unknown_id_returns_unknown_notebook(self, server):
        async with Client(server) as client:
            result = await client.call_tool(
                "get_notebook_status", {"notebook_id": "missing"}
            )
        assert result.structured_content["error"]["kind"] == "unknown_notebook"

    @pytest.mark.asyncio
    async def test_registered_without_session(self, server):
        registered()
        async with Client(server) as client:
            result = await client.call_tool(
                "get_notebook_status", {"notebook_id": "training"}
            )
        assert result.structured_content == {
            "notebook": {
                "notebook_id": "training",
                "name": "Training",
                "url": DRIVE_URL,
            },
            "session_exists": False,
            "connected": False,
            "active_notebook_url": None,
        }

    @pytest.mark.asyncio
    async def test_disconnected_session(self, server, manager):
        registered()
        await manager.get_or_create("training")
        async with Client(server) as client:
            result = await client.call_tool(
                "get_notebook_status", {"notebook_id": "training"}
            )
        assert result.structured_content["session_exists"] is True
        assert result.structured_content["connected"] is False

    @pytest.mark.asyncio
    async def test_connected_session_reports_active_url(self, server, manager):
        registered()
        session = await manager.get_or_create("training")
        session.proxy_client = mock_proxy_client()
        session.active_notebook_url = DRIVE_URL
        async with Client(server) as client:
            result = await client.call_tool(
                "get_notebook_status", {"notebook_id": "training"}
            )
        assert result.structured_content["session_exists"] is True
        assert result.structured_content["connected"] is True
        assert result.structured_content["active_notebook_url"] == DRIVE_URL


class TestOpenNotebook:
    @pytest.mark.asyncio
    async def test_registered_notebook_uses_managed_browser(
        self, manager, mock_webbrowser
    ):
        registered()
        browser = Mock(open_and_approve=AsyncMock())
        server = build_server(manager, browser=browser)

        async with Client(server) as client:
            await client.call_tool("open_notebook", {"notebook_id": "training"})

        browser.open_and_approve.assert_awaited_once()
        assert browser.open_and_approve.await_args.args[0] == "training"
        mock_webbrowser.assert_not_called()

    @pytest.mark.asyncio
    async def test_opens_registered_url_and_names_session(
        self, server, manager, mock_webbrowser
    ):
        registered()
        async with Client(server) as client:
            result = await client.call_tool(
                "open_notebook", {"notebook_id": "training"}
            )

        session = manager.get("training")
        opened = mock_webbrowser.call_args.args[0]
        assert opened.startswith(f"{DRIVE_URL}?{TAB_DEDUP_PARAM}={session.port}#")
        assert f"{PROXY_TOKEN_PARAM}={session.token}" in opened
        assert f"{PROXY_PORT_PARAM}={session.port}" in opened
        assert session.active_notebook_url == DRIVE_URL
        assert result.structured_content == {
            "connected": False,  # nothing ever connects in unit tests
            "notebook_id": "training",
            "notebook_url": DRIVE_URL,
        }

    @pytest.mark.asyncio
    async def test_unknown_id_returns_unknown_notebook(self, server, mock_webbrowser):
        async with Client(server) as client:
            result = await client.call_tool("open_notebook", {"notebook_id": "missing"})
        assert result.structured_content["error"]["kind"] == "unknown_notebook"
        mock_webbrowser.assert_not_called()

    @pytest.mark.asyncio
    async def test_already_connected_returns_without_reopening(
        self, server, manager, mock_webbrowser
    ):
        registered()
        session = await manager.get_or_create("training")
        session.proxy_client = mock_proxy_client()
        session.active_notebook_url = DRIVE_URL

        async with Client(server) as client:
            result = await client.call_tool(
                "open_notebook", {"notebook_id": "training"}
            )

        mock_webbrowser.assert_not_called()
        assert result.structured_content == {
            "connected": True,
            "notebook_id": "training",
            "notebook_url": DRIVE_URL,
        }

    @pytest.mark.asyncio
    async def test_session_connected_to_other_notebook_returns_invalid_input(
        self, server, manager, mock_webbrowser
    ):
        registered()
        session = await manager.get_or_create("training")
        session.proxy_client = mock_proxy_client()
        session.active_notebook_url = OTHER_URL  # live session on another notebook

        async with Client(server) as client:
            result = await client.call_tool(
                "open_notebook", {"notebook_id": "training"}
            )

        mock_webbrowser.assert_not_called()
        error = result.structured_content["error"]
        assert error["kind"] == "invalid_input"
        assert error["details"]["requested_notebook_url"] == DRIVE_URL

    @pytest.mark.asyncio
    async def test_reports_progress_while_waiting(self, server):
        registered()
        seen = []

        async def on_progress(progress, total, message):
            seen.append(message)

        async with Client(server) as client:
            await client.call_tool(
                "open_notebook",
                {"notebook_id": "training"},
                progress_handler=on_progress,
            )

        assert len(seen) == 3
        assert "Timeout" in seen[-1]


class TestCloseNotebook:
    @pytest.mark.asyncio
    async def test_closes_session_but_keeps_record(self, server, manager):
        registered()
        await manager.get_or_create("training")

        async with Client(server) as client:
            result = await client.call_tool(
                "close_notebook", {"notebook_id": "training"}
            )
            listed = await client.call_tool("list_notebooks", {})

        assert result.structured_content == {
            "closed": "training",
            "session_existed": True,
        }
        with pytest.raises(Exception, match="Unknown notebook_id"):
            manager.get("training")  # session is gone ...
        assert len(listed.structured_content["notebooks"]) == 1  # ... record stays

    @pytest.mark.asyncio
    async def test_registered_but_never_opened_closes_idempotently(self, server):
        registered()
        async with Client(server) as client:
            result = await client.call_tool(
                "close_notebook", {"notebook_id": "training"}
            )
        assert result.structured_content == {
            "closed": "training",
            "session_existed": False,
        }

    @pytest.mark.asyncio
    async def test_unregistered_id_returns_unknown_notebook(self, server, manager):
        await manager.get_or_create("rogue")  # a session without a registry record
        async with Client(server) as client:
            result = await client.call_tool("close_notebook", {"notebook_id": "rogue"})
        assert result.structured_content["error"]["kind"] == "unknown_notebook"
        manager.get("rogue")  # the unregistered session was not closed


class TestPersistenceAcrossRestart:
    @pytest.mark.asyncio
    async def test_registry_survives_server_restart(self, server):
        async with Client(server) as client:
            await client.call_tool(
                "register_notebook",
                {"notebook_id": "training", "name": "Training", "url": DRIVE_URL},
            )

        restarted_manager = SessionManager()
        try:
            async with Client(build_server(restarted_manager)) as client:
                result = await client.call_tool("list_notebooks", {})
        finally:
            await restarted_manager.aclose()

        assert result.structured_content == {
            "notebooks": [
                {"notebook_id": "training", "name": "Training", "url": DRIVE_URL}
            ]
        }
