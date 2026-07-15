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

import webbrowser
from unittest.mock import Mock

import pytest
import pytest_asyncio
from conftest import fake_raw_result, mock_proxy_client
from fastmcp import Client

from cool_colab_mcp.constants import (
    COLAB,
    NOTEBOOK_URL_ENV,
    PROXY_PORT_PARAM,
    PROXY_TOKEN_PARAM,
    SCRATCH_PATH,
    TAB_DEDUP_PARAM,
)
from cool_colab_mcp.server import build_server
from cool_colab_mcp.sessions.manager import SessionManager

DRIVE_URL = f"{COLAB}/drive/file-id-1"
GITHUB_URL = f"{COLAB}/github/user/repo/blob/main/nb.ipynb"

ALL_TOOLS = {
    "open_colab_browser_connection",
    "add_code_cell",
    "add_text_cell",
    "get_cells",
    "run_code_cell",
    "update_cell",
    "delete_cell",
    "move_cell",
}

NOTEBOOK_TOOL_CALLS = [
    ("add_code_cell", {"code": "1+1"}, {"code": "1+1"}),
    (
        "add_code_cell",
        {"code": "1+1", "cellIndex": 2, "language": "python"},
        {"code": "1+1", "cellIndex": 2, "language": "python"},
    ),
    ("add_text_cell", {"content": "# hi"}, {"content": "# hi"}),
    ("get_cells", {}, {}),
    ("run_code_cell", {"cellId": "c-1"}, {"cellId": "c-1"}),
    (
        "update_cell",
        {"cellId": "c-1", "content": "x=1"},
        {"cellId": "c-1", "content": "x=1"},
    ),
    ("delete_cell", {"cellId": "c-1"}, {"cellId": "c-1"}),
    ("move_cell", {"cellId": "c-1", "cellIndex": 3}, {"cellId": "c-1", "cellIndex": 3}),
]


@pytest.fixture(autouse=True)
def mock_webbrowser(monkeypatch):
    mock_open = Mock()
    monkeypatch.setattr(webbrowser, "open_new", mock_open)
    return mock_open


@pytest.fixture(autouse=True)
def fast_timeout(monkeypatch):
    monkeypatch.setattr("cool_colab_mcp.server.UI_CONNECTION_TIMEOUT", 0.05)
    monkeypatch.delenv(NOTEBOOK_URL_ENV, raising=False)


@pytest_asyncio.fixture
async def manager():
    manager = SessionManager()
    yield manager
    await manager.aclose()


@pytest.fixture
def server(manager):
    return build_server(manager)


async def connect(manager, notebook_id=None, results=None):
    """Create a session and mark it connected via a mocked proxy client."""
    session = await manager.get_or_create(notebook_id)
    session.proxy_client = mock_proxy_client(results)
    return session


class TestStaticToolSurface:
    @pytest.mark.asyncio
    async def test_all_tools_listed_while_disconnected(self, server):
        async with Client(server) as client:
            tools = await client.list_tools()
        assert {tool.name for tool in tools} == ALL_TOOLS

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name,args,_", NOTEBOOK_TOOL_CALLS)
    async def test_notebook_tool_disconnected_returns_not_connected(
        self, server, name, args, _
    ):
        async with Client(server) as client:
            result = await client.call_tool(name, args)
        assert result.structured_content["error"]["kind"] == "not_connected"

    @pytest.mark.asyncio
    async def test_unknown_notebook_id_returns_structured_error(self, server, manager):
        await connect(manager)
        async with Client(server) as client:
            result = await client.call_tool("get_cells", {"notebook_id": "missing"})
        error = result.structured_content["error"]
        assert error["kind"] == "unknown_notebook"
        assert error["details"] == {"notebook_id": "missing"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name,args,forwarded", NOTEBOOK_TOOL_CALLS)
    async def test_connected_tool_forwards_to_proxy_client(
        self, server, manager, name, args, forwarded
    ):
        session = await connect(manager, results=[fake_raw_result({"ok": True})])
        async with Client(server) as client:
            result = await client.call_tool(name, args)

        session.proxy_client.call_tool.assert_awaited_once_with(name, forwarded)
        assert result.structured_content == {"ok": True}

    @pytest.mark.asyncio
    async def test_tool_routes_to_the_session_named_by_notebook_id(
        self, server, manager
    ):
        default = await connect(manager)
        other = await connect(manager, "nb-b", [fake_raw_result({"from": "b"})])

        async with Client(server) as client:
            result = await client.call_tool("get_cells", {"notebook_id": "nb-b"})

        assert result.structured_content == {"from": "b"}
        other.proxy_client.call_tool.assert_awaited_once()
        default.proxy_client.call_tool.assert_not_awaited()


class TestOpenColabBrowserConnection:
    @pytest.mark.asyncio
    async def test_explicit_url_opens_tab_and_becomes_active(
        self, server, manager, mock_webbrowser
    ):
        async with Client(server) as client:
            result = await client.call_tool(
                "open_colab_browser_connection", {"notebook_url": DRIVE_URL}
            )

        session = manager.get()
        opened = mock_webbrowser.call_args.args[0]
        assert opened.startswith(f"{DRIVE_URL}?{TAB_DEDUP_PARAM}={session.port}#")
        assert f"{PROXY_TOKEN_PARAM}={session.token}" in opened
        assert f"{PROXY_PORT_PARAM}={session.port}" in opened
        assert session.active_notebook_url == DRIVE_URL
        assert result.structured_content == {
            "connected": False,  # nothing ever connects in unit tests
            "notebook_id": "default",
            "notebook_url": DRIVE_URL,
        }

    @pytest.mark.asyncio
    async def test_url_carries_port_param_before_the_fragment(
        self, server, manager, mock_webbrowser
    ):
        """Chrome dedupes tabs by URL-without-fragment; `?p=<port>` makes each
        server's URL unique so a stale tab pointing at a dead port is never
        reused."""
        async with Client(server) as client:
            await client.call_tool(
                "open_colab_browser_connection", {"notebook_url": DRIVE_URL}
            )

        session = manager.get()
        opened = mock_webbrowser.call_args.args[0]
        base, _, fragment = opened.partition("#")
        assert base == f"{DRIVE_URL}?{TAB_DEDUP_PARAM}={session.port}"
        assert fragment == (
            f"{PROXY_TOKEN_PARAM}={session.token}&{PROXY_PORT_PARAM}={session.port}"
        )

    @pytest.mark.asyncio
    async def test_port_param_appends_to_an_existing_query(
        self, server, manager, mock_webbrowser
    ):
        url = f"{DRIVE_URL}?usp=sharing"
        async with Client(server) as client:
            await client.call_tool(
                "open_colab_browser_connection", {"notebook_url": url}
            )

        session = manager.get()
        opened = mock_webbrowser.call_args.args[0]
        assert opened.startswith(f"{url}&{TAB_DEDUP_PARAM}={session.port}#")

    @pytest.mark.asyncio
    async def test_github_url_accepted_with_caveat_documented(self, server):
        async with Client(server) as client:
            tools = {t.name: t for t in await client.list_tools()}
            result = await client.call_tool(
                "open_colab_browser_connection", {"notebook_url": GITHUB_URL}
            )
        assert result.structured_content["notebook_url"] == GITHUB_URL
        description = tools["open_colab_browser_connection"].description
        assert "pushed" in description  # the GitHub remote-branch caveat

    @pytest.mark.asyncio
    async def test_invalid_url_returns_invalid_input_and_creates_no_session(
        self, server, manager, mock_webbrowser
    ):
        async with Client(server) as client:
            result = await client.call_tool(
                "open_colab_browser_connection",
                {"notebook_url": "https://evil.com/drive/x"},
            )
        assert result.structured_content["error"]["kind"] == "invalid_input"
        mock_webbrowser.assert_not_called()
        with pytest.raises(Exception, match="No Colab connection yet"):
            manager.get()

    @pytest.mark.asyncio
    async def test_reconnect_without_parameter_returns_to_active(
        self, server, mock_webbrowser
    ):
        async with Client(server) as client:
            await client.call_tool(
                "open_colab_browser_connection", {"notebook_url": DRIVE_URL}
            )
            await client.call_tool("open_colab_browser_connection", {})

        reopened = mock_webbrowser.call_args.args[0]
        assert reopened.startswith(f"{DRIVE_URL}?")

    @pytest.mark.asyncio
    async def test_env_pin_fallback(self, server, monkeypatch, mock_webbrowser):
        monkeypatch.setenv(NOTEBOOK_URL_ENV, f"{COLAB}/drive/env-pin")
        async with Client(server) as client:
            await client.call_tool("open_colab_browser_connection", {})
        assert mock_webbrowser.call_args.args[0].startswith(f"{COLAB}/drive/env-pin?")

    @pytest.mark.asyncio
    async def test_scratch_fallback(self, server, mock_webbrowser):
        async with Client(server) as client:
            await client.call_tool("open_colab_browser_connection", {})
        assert mock_webbrowser.call_args.args[0].startswith(f"{COLAB}{SCRATCH_PATH}?")

    @pytest.mark.asyncio
    async def test_already_connected_returns_without_reopening(
        self, server, manager, mock_webbrowser
    ):
        session = await connect(manager)
        session.active_notebook_url = DRIVE_URL

        async with Client(server) as client:
            result = await client.call_tool("open_colab_browser_connection", {})

        mock_webbrowser.assert_not_called()
        assert result.structured_content == {
            "connected": True,
            "notebook_id": "default",
            "notebook_url": DRIVE_URL,
        }

    @pytest.mark.asyncio
    async def test_connected_session_rejects_conflicting_notebook_url(
        self, server, manager, mock_webbrowser
    ):
        session = await connect(manager)
        session.active_notebook_url = DRIVE_URL

        async with Client(server) as client:
            result = await client.call_tool(
                "open_colab_browser_connection",
                {"notebook_url": f"{COLAB}/drive/another-notebook"},
            )

        mock_webbrowser.assert_not_called()
        error = result.structured_content["error"]
        assert error["kind"] == "invalid_input"
        assert error["details"]["active_notebook_url"] == DRIVE_URL
        assert (
            error["details"]["requested_notebook_url"]
            == f"{COLAB}/drive/another-notebook"
        )

    @pytest.mark.asyncio
    async def test_notebook_id_creates_an_independent_session(self, server, manager):
        async with Client(server) as client:
            await client.call_tool(
                "open_colab_browser_connection",
                {"notebook_url": DRIVE_URL, "notebook_id": "nb-a"},
            )
            await client.call_tool(
                "open_colab_browser_connection",
                {"notebook_url": GITHUB_URL, "notebook_id": "nb-b"},
            )

        assert manager.get("nb-a").active_notebook_url == DRIVE_URL
        assert manager.get("nb-b").active_notebook_url == GITHUB_URL
        assert manager.get("nb-a").port != manager.get("nb-b").port

    @pytest.mark.asyncio
    async def test_reports_progress_while_waiting(self, server):
        seen = []

        async def on_progress(progress, total, message):
            seen.append(message)

        async with Client(server) as client:
            await client.call_tool(
                "open_colab_browser_connection",
                {"notebook_url": DRIVE_URL},
                progress_handler=on_progress,
            )

        assert len(seen) == 3
        assert "Timeout" in seen[-1]
