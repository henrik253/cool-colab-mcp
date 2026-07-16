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

"""Managed Chromium that opens notebook tabs and auto-approves the MCP dialog.

Replaces the fire-and-forget `webbrowser.open_new`: this owns the page, so it can
approve the connect dialog and map each tab to a notebook_id (plan.md §10/§11).
"""

import logging

from cool_colab_mcp.browser.adapters.colab import approval
from cool_colab_mcp.constants import (
    AUTOMATION_FLAG,
    BROWSER_PROFILE_DIR_NAME,
    CHROME_CHANNEL,
    COLAB,
    DIALOG_TIMEOUT_MS,
    LOCAL_NETWORK_PERMISSION,
)
from cool_colab_mcp.errors import fail
from cool_colab_mcp.storage import base_dir

logger = logging.getLogger(__name__)


class BrowserController:
    """One managed Chromium, one page per notebook_id."""

    def __init__(
        self,
        headless: bool = False,
        use_chrome: bool = True,
        cdp_url: str | None = None,
    ):
        self.headless = headless
        # Real Chrome by default: Google refuses sign-in in Playwright's bundled
        # Chromium, so a profile there can never become useful.
        self.use_chrome = use_chrome
        # Attach to a Chrome the operator started themselves (and signed into)
        # instead of launching one. The most reliable route past Google's
        # automated-browser sign-in check.
        self.cdp_url = cdp_url
        self._playwright = None
        self._context = None
        self._owns_browser = True
        self._browser = None
        self._pages: dict[str, object] = {}

    async def start(self) -> None:
        """Launch Chrome with the persistent profile, or attach to a running one."""
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise fail(
                "user_action_required",
                "Browser automation needs Playwright. Install it with "
                "'uv sync' and 'uv run playwright install chromium'.",
            ) from exc

        self._playwright = await async_playwright().start()
        if self.cdp_url:
            # The operator owns this browser; we only drive it.
            self._browser = await self._playwright.chromium.connect_over_cdp(
                self.cdp_url
            )
            self._owns_browser = False
            self._context = (
                self._browser.contexts[0]
                if self._browser.contexts
                else await self._browser.new_context()
            )
        else:
            # A persistent profile keeps the Google login across restarts
            # (plan.md §3/§10).
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(base_dir() / BROWSER_PROFILE_DIR_NAME),
                headless=self.headless,
                channel=CHROME_CHANNEL if self.use_chrome else None,
                # Google's sign-in refuses browsers advertising automation.
                ignore_default_args=[AUTOMATION_FLAG],
            )
        # Chrome's Local Network Access gate gives Colab (a public origin) permission to
        # reach our localhost server. Scoped to the Colab origin only; without it the
        # dialog is accepted but the WebSocket dies with ERR_BLOCKED_BY_LOCAL_NETWORK.
        try:
            await self._context.grant_permissions(
                [LOCAL_NETWORK_PERMISSION], origin=COLAB
            )
        except Exception:
            # Older Chrome builds lack the Local Network Access permission; the
            # connection then fails visibly at approval time rather than silently here.
            logger.warning(
                "could not pre-grant %s; Colab may be blocked from reaching localhost",
                LOCAL_NETWORK_PERMISSION,
            )
        logger.info(
            "browser started (headless=%s, chrome=%s, attached=%s)",
            self.headless,
            self.use_chrome,
            bool(self.cdp_url),
        )

    async def open_and_approve(
        self, notebook_id: str, url: str, token: str, port: int
    ) -> None:
        """Open `url` in this notebook's tab and accept the MCP dialog for it.

        Returns once Connect has been clicked; the caller awaits the session's own
        connection signal to decide success.
        """
        if self._context is None:
            raise fail("not_connected", "Browser controller is not started.")

        page = self._pages.get(notebook_id)
        if page is None:
            page = await self._context.new_page()
            self._pages[notebook_id] = page

        await page.goto(url, wait_until="domcontentloaded")
        logger.info("opened notebook tab (notebook_id=%s, port=%d)", notebook_id, port)
        await approval.approve(page, token, port, DIALOG_TIMEOUT_MS)
        logger.info("approved MCP dialog (notebook_id=%s)", notebook_id)

    async def open_page(self, url: str):
        """Open a standalone page with no approval flow.

        Used for the one-time Google sign-in: the user signs in themselves and the
        persistent profile keeps the session for later automated runs.
        """
        if self._context is None:
            raise fail("not_connected", "Browser controller is not started.")
        # A persistent context starts with one blank page; reuse it so the operator
        # sees a single window rather than a stray blank tab beside the real one.
        page = (
            self._context.pages[0]
            if self._context.pages
            else await self._context.new_page()
        )
        await page.goto(url, wait_until="domcontentloaded")
        return page

    async def close(self, notebook_id: str) -> None:
        """Close one notebook's tab."""
        page = self._pages.pop(notebook_id, None)
        if page is not None:
            await page.close()

    async def aclose(self) -> None:
        """Shut down what we started; never close a browser the operator owns."""
        self._pages.clear()
        if self._context is not None and self._owns_browser:
            await self._context.close()
        self._context = None
        self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
