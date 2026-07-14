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

"""Shared test doubles for the WebSocket/proxy boundary."""

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from mcp.types import TextContent


class MockColabWebSocketServer:
    def __init__(self):
        self.connection_live = asyncio.Event()
        self.read_stream = AsyncMock()
        self.write_stream = AsyncMock()
        self.token = "test-token"
        self.port = 1234

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.fixture
def mock_wss():
    """Provides a mock ColabWebSocketServer instance."""
    return MockColabWebSocketServer()


def fake_raw_result(structured: dict[str, Any] | None = None, text: str = "ok"):
    """A stand-in for the CallToolResult a proxy client returns."""
    return SimpleNamespace(
        content=[TextContent(type="text", text=text)], structured_content=structured
    )


def mock_proxy_client(results: list | None = None) -> Mock:
    """A connected proxy-client mock; call_tool yields `results` in order."""
    proxy = Mock()
    proxy.is_connected.return_value = True
    proxy.call_tool = AsyncMock(
        side_effect=results
        if results is not None
        else lambda *a, **kw: fake_raw_result()
    )
    return proxy
