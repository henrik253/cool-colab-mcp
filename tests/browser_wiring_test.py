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

"""open_connection routes through the managed browser when one is attached."""

import webbrowser
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from fastmcp import Client

from cool_colab_mcp.constants import COLAB, NOTEBOOK_URL_ENV, PROXY_TOKEN_PARAM
from cool_colab_mcp.errors import fail
from cool_colab_mcp.server import build_server
from cool_colab_mcp.sessions.manager import SessionManager

DRIVE_URL = f"{COLAB}/drive/file-id-1"


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
async def manager_with_browser():
    browser = Mock(open_and_approve=AsyncMock())
    manager = SessionManager(browser=browser)
    yield manager, browser
    await manager.aclose()


class TestManagedBrowserWiring:
    @pytest.mark.asyncio
    async def test_opens_via_browser_and_not_webbrowser(
        self, manager_with_browser, mock_webbrowser
    ):
        manager, browser = manager_with_browser
        async with Client(build_server(manager)) as client:
            await client.call_tool(
                "open_colab_browser_connection", {"notebook_url": DRIVE_URL}
            )

        mock_webbrowser.assert_not_called()
        browser.open_and_approve.assert_awaited_once()
        notebook_id, url, token, port = browser.open_and_approve.await_args.args
        session = manager.get()
        assert notebook_id == session.notebook_id
        assert (token, port) == (session.token, session.port)
        assert url.startswith(DRIVE_URL)
        assert f"{PROXY_TOKEN_PARAM}={session.token}" in url

    @pytest.mark.asyncio
    async def test_approval_failure_returns_structured_error(
        self, manager_with_browser
    ):
        manager, browser = manager_with_browser
        browser.open_and_approve = AsyncMock(
            side_effect=fail("user_action_required", "dialog never appeared")
        )
        async with Client(build_server(manager)) as client:
            result = await client.call_tool(
                "open_colab_browser_connection", {"notebook_url": DRIVE_URL}
            )
        assert result.structured_content["error"]["kind"] == "user_action_required"

    @pytest.mark.asyncio
    async def test_without_browser_falls_back_to_webbrowser(self, mock_webbrowser):
        manager = SessionManager()
        try:
            async with Client(build_server(manager)) as client:
                await client.call_tool(
                    "open_colab_browser_connection", {"notebook_url": DRIVE_URL}
                )
            mock_webbrowser.assert_called_once()
        finally:
            await manager.aclose()
