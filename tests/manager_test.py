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

import asyncio

import pytest
import pytest_asyncio
from conftest import fake_raw_result, mock_proxy_client

from cool_colab_mcp.constants import DEFAULT_NOTEBOOK_ID
from cool_colab_mcp.errors import ToolFailed
from cool_colab_mcp.sessions.manager import SessionManager


@pytest_asyncio.fixture
async def manager():
    manager = SessionManager()
    yield manager
    await manager.aclose()


class TestGetOrCreate:
    @pytest.mark.asyncio
    async def test_without_id_creates_the_default_session(self, manager):
        session = await manager.get_or_create()
        assert session.notebook_id == DEFAULT_NOTEBOOK_ID
        assert manager.get() is session

    @pytest.mark.asyncio
    async def test_same_id_returns_same_session(self, manager):
        assert await manager.get_or_create("nb") is await manager.get_or_create("nb")

    @pytest.mark.asyncio
    async def test_sessions_have_own_server_token_and_port(self, manager):
        first = await manager.get_or_create("nb-a")
        second = await manager.get_or_create("nb-b")
        assert first.wss is not second.wss
        assert first.token != second.token
        assert first.port != second.port


class TestGet:
    @pytest.mark.asyncio
    async def test_unknown_id_raises_structured_error(self, manager):
        with pytest.raises(ToolFailed) as exc_info:
            manager.get("missing")
        assert exc_info.value.error.kind == "unknown_notebook"
        assert exc_info.value.error.details == {"notebook_id": "missing"}

    @pytest.mark.asyncio
    async def test_without_id_before_any_open_raises_not_connected(self, manager):
        with pytest.raises(ToolFailed) as exc_info:
            manager.get()
        assert exc_info.value.error.kind == "not_connected"

    @pytest.mark.asyncio
    async def test_returns_existing_session(self, manager):
        session = await manager.get_or_create("nb")
        assert manager.get("nb") is session


class TestRouting:
    @pytest.mark.asyncio
    async def test_two_sessions_route_independently(self, manager):
        first = await manager.get_or_create("nb-a")
        second = await manager.get_or_create("nb-b")
        first.proxy_client = mock_proxy_client([fake_raw_result({"from": "a"})])
        second.proxy_client = mock_proxy_client([fake_raw_result({"from": "b"})])

        result_a = await manager.get("nb-a").call_tool("get_cells", {})
        result_b = await manager.get("nb-b").call_tool("get_cells", {})

        assert result_a.structured_content == {"from": "a"}
        assert result_b.structured_content == {"from": "b"}
        first.proxy_client.call_tool.assert_awaited_once()
        second.proxy_client.call_tool.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sessions_operate_concurrently(self, manager):
        """One session's held lock must not block another session's operations."""
        blocked = await manager.get_or_create("nb-a")
        free = await manager.get_or_create("nb-b")
        free.proxy_client = mock_proxy_client()

        await blocked.lock.acquire()
        try:
            await asyncio.wait_for(free.call_tool("get_cells", {}), timeout=1)
        finally:
            blocked.lock.release()


class TestClose:
    @pytest.mark.asyncio
    async def test_close_forgets_the_session(self, manager):
        await manager.get_or_create("nb")
        await manager.close("nb")
        with pytest.raises(ToolFailed):
            manager.get("nb")

    @pytest.mark.asyncio
    async def test_close_unknown_id_raises_structured_error(self, manager):
        with pytest.raises(ToolFailed) as exc_info:
            await manager.close("missing")
        assert exc_info.value.error.kind == "unknown_notebook"

    @pytest.mark.asyncio
    async def test_aclose_shuts_every_session(self, manager):
        await manager.get_or_create("nb-a")
        await manager.get_or_create("nb-b")
        await manager.aclose()
        with pytest.raises(ToolFailed):
            manager.get("nb-a")
