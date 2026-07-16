from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from cool_colab_mcp.browser.controller import ManagedBrowser
from cool_colab_mcp.errors import ToolFailed


def fake_playwright(page=None, launch_error=None):
    page = page or Mock(is_closed=Mock(return_value=False), goto=AsyncMock())
    context = Mock(new_page=AsyncMock(return_value=page), close=AsyncMock(), pages=[])
    launch = AsyncMock(return_value=context, side_effect=launch_error)
    playwright = SimpleNamespace(
        chromium=SimpleNamespace(launch_persistent_context=launch),
        stop=AsyncMock(),
    )
    starter = Mock(start=AsyncMock(return_value=playwright))
    return starter, playwright, context, page


@pytest.mark.asyncio
async def test_persistent_context_and_page_reused(tmp_path, monkeypatch):
    starter, playwright, context, page = fake_playwright()
    approve = AsyncMock()
    monkeypatch.setattr(
        "cool_colab_mcp.browser.controller.async_playwright", lambda: starter
    )
    monkeypatch.setattr(
        "cool_colab_mcp.browser.controller.approve_mcp_connection", approve
    )
    browser = ManagedBrowser(profile_dir=tmp_path / "profile")

    await browser.open_and_approve("nb-a", "full-1", "notebook-1", "token-1", 1)
    await browser.open_and_approve("nb-a", "full-2", "notebook-1", "token-2", 2)
    await browser.aclose()

    playwright.chromium.launch_persistent_context.assert_awaited_once_with(
        tmp_path / "profile", headless=False
    )
    context.new_page.assert_awaited_once()
    assert page.goto.await_args_list[0].args == ("full-1",)
    assert page.goto.await_args_list[1].args == ("full-2",)
    assert approve.await_count == 2
    context.close.assert_awaited_once()
    playwright.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_distinct_notebooks_get_distinct_pages(tmp_path, monkeypatch):
    page_a = Mock(is_closed=Mock(return_value=False), goto=AsyncMock())
    page_b = Mock(is_closed=Mock(return_value=False), goto=AsyncMock())
    starter, _, context, _ = fake_playwright(page_a)
    context.new_page = AsyncMock(side_effect=[page_a, page_b])
    monkeypatch.setattr(
        "cool_colab_mcp.browser.controller.async_playwright", lambda: starter
    )
    monkeypatch.setattr(
        "cool_colab_mcp.browser.controller.approve_mcp_connection", AsyncMock()
    )
    browser = ManagedBrowser(profile_dir=tmp_path / "profile")

    await browser.open_and_approve("nb-a", "a", "na", "ta", 1)
    await browser.open_and_approve("nb-b", "b", "nb", "tb", 2)

    assert context.new_page.await_count == 2


@pytest.mark.asyncio
async def test_missing_chromium_is_actionable(tmp_path, monkeypatch):
    starter, _, _, _ = fake_playwright(launch_error=RuntimeError("missing executable"))
    monkeypatch.setattr(
        "cool_colab_mcp.browser.controller.async_playwright", lambda: starter
    )
    browser = ManagedBrowser(profile_dir=tmp_path / "profile")

    with pytest.raises(ToolFailed) as failure:
        await browser.start()

    assert failure.value.error.kind == "user_action_required"
    assert "playwright install chromium" in failure.value.error.message
