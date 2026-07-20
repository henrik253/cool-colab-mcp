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

"""The verified MCP-dialog approval (plan.md §11). No browser, no network."""

from unittest.mock import AsyncMock, Mock

import pytest

from cool_colab_mcp.browser.adapters.colab import approval
from cool_colab_mcp.browser.adapters.colab.constants import CONNECT_BUTTON, TOKEN_FIELD
from cool_colab_mcp.constants import COLAB
from cool_colab_mcp.errors import ToolFailed

TOKEN = "tok-abc123"
PORT = 54321


def fake_page(origin=COLAB, shown=f"{TOKEN}&{PORT}", dialog_raises=None):
    """A Playwright page double: the dialog, its token field, and the Connect button."""
    page = Mock()
    page.wait_for_selector = AsyncMock(side_effect=dialog_raises)
    page.evaluate = AsyncMock(return_value=origin)

    button = Mock(click=AsyncMock())
    field = Mock(get_attribute=AsyncMock(return_value=shown))
    page.locator = Mock(side_effect=lambda sel: field if sel == TOKEN_FIELD else button)
    page._button = button
    return page


class TestApprove:
    @pytest.mark.asyncio
    async def test_clicks_connect_when_dialog_is_ours(self):
        page = fake_page()
        await approval.approve(page, TOKEN, PORT, 1000)
        page._button.click.assert_awaited_once()
        page.locator.assert_any_call(CONNECT_BUTTON)

    @pytest.mark.asyncio
    async def test_missing_dialog_is_user_action_required(self):
        page = fake_page(dialog_raises=TimeoutError("no dialog"))
        with pytest.raises(ToolFailed) as failure:
            await approval.approve(page, TOKEN, PORT, 1000)
        assert failure.value.error.kind == "user_action_required"
        page._button.click.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refuses_unexpected_origin(self):
        page = fake_page(origin="https://evil.example.com")
        with pytest.raises(ToolFailed) as failure:
            await approval.approve(page, TOKEN, PORT, 1000)
        assert failure.value.error.kind == "invalid_input"
        page._button.click.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refuses_when_dialog_shows_another_sessions_token(self):
        page = fake_page(shown=f"someone-elses-token&{PORT}")
        with pytest.raises(ToolFailed) as failure:
            await approval.approve(page, TOKEN, PORT, 1000)
        assert failure.value.error.kind == "invalid_input"
        page._button.click.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refuses_when_dialog_shows_another_port(self):
        page = fake_page(shown=f"{TOKEN}&9999")
        with pytest.raises(ToolFailed):
            await approval.approve(page, TOKEN, PORT, 1000)
        page._button.click.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refusal_never_leaks_the_token(self):
        page = fake_page(shown=f"other&{PORT}")
        with pytest.raises(ToolFailed) as failure:
            await approval.approve(page, TOKEN, PORT, 1000)
        error = failure.value.error
        blob = f"{error.message}{error.details}"
        assert TOKEN not in blob
