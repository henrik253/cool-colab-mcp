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

"""Shared test doubles for the WebSocket/proxy and keyring/auth boundaries."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import keyring
import keyring.errors
import pytest
from google.oauth2.credentials import Credentials
from mcp.types import TextContent

from cool_colab_mcp.constants import HOME_ENV, OAUTH_SCOPES

# A recognizable fake access token; leak tests assert it never surfaces anywhere.
SENTINEL_TOKEN = "sentinel-access-token-must-never-leak"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Keep every test away from the user's real ~/.cool-colab-mcp state."""
    monkeypatch.setenv(HOME_ENV, str(tmp_path))
    return tmp_path


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


@pytest.fixture
def fake_keyring(monkeypatch) -> dict[tuple[str, str], str]:
    """An in-memory keyring; unit tests never touch the real OS keyring."""
    store: dict[tuple[str, str], str] = {}

    def set_password(service: str, account: str, value: str) -> None:
        store[(service, account)] = value

    def get_password(service: str, account: str) -> str | None:
        return store.get((service, account))

    def delete_password(service: str, account: str) -> None:
        if (service, account) not in store:
            raise keyring.errors.PasswordDeleteError(account)
        del store[(service, account)]

    monkeypatch.setattr(keyring, "set_password", set_password)
    monkeypatch.setattr(keyring, "get_password", get_password)
    monkeypatch.setattr(keyring, "delete_password", delete_password)
    return store


def make_credentials(
    token: str = SENTINEL_TOKEN,
    refresh_token: str | None = "test-refresh-token",
    expires_in: timedelta | None = None,
) -> Credentials:
    """Fake Google OAuth credentials; expires_in=None means no expiry (valid)."""
    expiry = None
    if expires_in is not None:
        # google-auth expects naive UTC datetimes for expiry
        expiry = datetime.now(UTC).replace(tzinfo=None) + expires_in
    return Credentials(
        token=token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id="test-client-id",
        client_secret="test-client-secret",
        scopes=list(OAUTH_SCOPES),
        expiry=expiry,
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
