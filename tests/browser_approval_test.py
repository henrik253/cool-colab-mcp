from unittest.mock import AsyncMock, Mock

import pytest

from cool_colab_mcp.browser.adapters.colab.approval import (
    approve_mcp_connection,
    verify_connection_page,
)
from cool_colab_mcp.constants import COLAB
from cool_colab_mcp.errors import ToolFailed

NOTEBOOK_URL = f"{COLAB}/drive/notebook-a"
TOKEN = "session-token"
PORT = 4321
CONNECTION_URL = f"{NOTEBOOK_URL}?p={PORT}#mcpProxyToken={TOKEN}&mcpProxyPort={PORT}"


def test_verified_page_accepts_exact_session():
    verify_connection_page(CONNECTION_URL, NOTEBOOK_URL, TOKEN, PORT)


@pytest.mark.parametrize(
    "page_url",
    [
        f"https://evil.example/drive/notebook-a#"
        f"mcpProxyToken={TOKEN}&mcpProxyPort={PORT}",
        f"{COLAB}/drive/notebook-b#mcpProxyToken={TOKEN}&mcpProxyPort={PORT}",
        f"{NOTEBOOK_URL}#mcpProxyToken=wrong&mcpProxyPort={PORT}",
        f"{NOTEBOOK_URL}#mcpProxyToken={TOKEN}&mcpProxyPort=9999",
    ],
)
def test_unverified_page_is_actionable_and_leaks_no_token(page_url):
    with pytest.raises(ToolFailed) as failure:
        verify_connection_page(page_url, NOTEBOOK_URL, TOKEN, PORT)
    assert failure.value.error.kind == "user_action_required"
    assert TOKEN not in failure.value.error.message


@pytest.mark.asyncio
async def test_clicks_only_continue_inside_named_dialog():
    button = Mock(click=AsyncMock())
    dialog = Mock()
    dialog.get_by_role.return_value = button
    page = Mock(url=CONNECTION_URL)
    dialogs = Mock()
    dialogs.filter.return_value = dialog
    page.get_by_role.return_value = dialogs

    await approve_mcp_connection(page, NOTEBOOK_URL, TOKEN, PORT)

    page.get_by_role.assert_called_once_with("dialog")
    dialogs.filter.assert_called_once_with(has_text="Colab MCP")
    dialog.get_by_role.assert_called_once_with("button", name="Continue", exact=True)
    button.click.assert_awaited_once()


@pytest.mark.asyncio
async def test_changed_ui_returns_user_action_required(monkeypatch):
    monkeypatch.setattr(
        "cool_colab_mcp.browser.adapters.colab.approval.BROWSER_RETRY_DELAY", 0
    )
    button = Mock(click=AsyncMock(side_effect=TimeoutError))
    dialog = Mock()
    dialog.get_by_role.return_value = button
    page = Mock(url=CONNECTION_URL)
    dialogs = Mock()
    dialogs.filter.return_value = dialog
    page.get_by_role.return_value = dialogs

    with pytest.raises(ToolFailed) as failure:
        await approve_mcp_connection(page, NOTEBOOK_URL, TOKEN, PORT)

    assert failure.value.error.kind == "user_action_required"
    assert button.click.await_count == 3
