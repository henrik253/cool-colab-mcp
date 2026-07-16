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

"""Exported browser sessions: a credential, so file mode and failure modes matter."""

import json
import stat
from unittest.mock import AsyncMock, Mock

import pytest

from cool_colab_mcp.browser.controller import BrowserController
from cool_colab_mcp.errors import ToolFailed

STATE = {
    "cookies": [
        {"name": "SID", "value": "secret-cookie-value", "domain": ".google.com"},
        {"name": "HSID", "value": "another-secret", "domain": ".google.com"},
    ],
    "origins": [],
}


def controller_with_context(state=STATE):
    controller = BrowserController()
    controller._context = Mock(storage_state=AsyncMock(return_value=state))
    return controller


class TestExportSession:
    @pytest.mark.asyncio
    async def test_writes_state_and_returns_cookie_count(self, tmp_path):
        path = tmp_path / "session.json"
        count = await controller_with_context().export_session(path)
        assert count == 2
        assert json.loads(path.read_text())["cookies"][0]["name"] == "SID"

    @pytest.mark.asyncio
    async def test_file_is_owner_only(self, tmp_path):
        # The file authenticates as the user with no password or 2FA.
        path = tmp_path / "session.json"
        await controller_with_context().export_session(path)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    @pytest.mark.asyncio
    async def test_creates_missing_parent_directory(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "session.json"
        await controller_with_context().export_session(path)
        assert path.exists()

    @pytest.mark.asyncio
    async def test_export_before_start_is_structured(self, tmp_path):
        with pytest.raises(ToolFailed) as failure:
            await BrowserController().export_session(tmp_path / "s.json")
        assert failure.value.error.kind == "not_connected"

    @pytest.mark.asyncio
    async def test_cookie_values_never_logged(self, tmp_path, caplog):
        with caplog.at_level("DEBUG"):
            await controller_with_context().export_session(tmp_path / "session.json")
        assert "secret-cookie-value" not in caplog.text


class TestMissingSessionFile:
    @pytest.mark.asyncio
    async def test_absent_session_is_user_action_required(self, tmp_path):
        controller = BrowserController(session_file=tmp_path / "nope.json")
        with pytest.raises(ToolFailed) as failure:
            await controller.start()
        error = failure.value.error
        assert error.kind == "user_action_required"
        assert "export-session" in error.message
