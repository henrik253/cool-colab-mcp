"""Playwright-managed Chromium with one persistent profile and mapped notebook tabs."""

import contextlib
import logging
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from cool_colab_mcp.browser.adapters.colab import approve_mcp_connection
from cool_colab_mcp.constants import BROWSER_PROFILE_DIR_NAME
from cool_colab_mcp.errors import ToolFailed, fail
from cool_colab_mcp.storage import base_dir

logger = logging.getLogger(__name__)


class ManagedBrowser:
    """Own a persistent Chromium context and map each notebook_id to one page."""

    def __init__(self, headless: bool = False, profile_dir: Path | None = None):
        self.headless = headless
        self.profile_dir = profile_dir or base_dir() / BROWSER_PROFILE_DIR_NAME
        self._playwright: Any = None
        self._context: Any = None
        self._pages: dict[str, Any] = {}

    async def start(self) -> None:
        if self._context is not None:
            return
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._playwright = await async_playwright().start()
            self._context = await self._playwright.chromium.launch_persistent_context(
                self.profile_dir, headless=self.headless
            )
        except Exception:
            await self.aclose()
            raise fail(
                "user_action_required",
                "Managed Chromium could not start. Run 'uv run playwright install chromium' "
                "and try again.",
            ) from None

    async def open_and_approve(
        self,
        notebook_id: str,
        connection_url: str,
        notebook_url: str,
        token: str,
        port: int,
    ) -> None:
        await self.start()
        page = self._pages.get(notebook_id)
        if page is None or page.is_closed():
            page = await self._context.new_page()
            self._pages[notebook_id] = page
        try:
            await page.goto(connection_url, wait_until="domcontentloaded")
            await approve_mcp_connection(page, notebook_url, token, port)
        except ToolFailed:
            raise
        except Exception:
            raise fail(
                "user_action_required",
                "Managed Chromium could not open the requested Colab notebook. "
                "Check the browser window and try again.",
            ) from None
        logger.info("Approved managed Colab tab for notebook '%s'", notebook_id)

    async def aclose(self) -> None:
        if self._context is not None:
            with contextlib.suppress(Exception):
                await self._context.close()
        if self._playwright is not None:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
        self._context = None
        self._playwright = None
        self._pages.clear()
