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

"""SessionManager — routes notebook_id → NotebookSession (plan.md §6)."""

import asyncio
import logging

from cool_colab_mcp.constants import DEFAULT_NOTEBOOK_ID
from cool_colab_mcp.errors import fail
from cool_colab_mcp.sessions.session import NotebookSession

logger = logging.getLogger(__name__)


class SessionManager:
    """Owns every NotebookSession; one complete, independent session per notebook.

    A None notebook_id targets the default session, preserving the single-notebook UX.
    """

    def __init__(self, browser=None) -> None:
        self._sessions: dict[str, NotebookSession] = {}
        self._create_lock = asyncio.Lock()
        # Optional BrowserController: when set, notebook tabs are opened in a managed
        # Chromium that auto-approves Colab's MCP dialog (plan.md §11). Without it we
        # fall back to webbrowser.open_new and the user clicks Connect themselves.
        # Its lifecycle belongs to whoever constructed it.
        self.browser = browser

    def get(self, notebook_id: str | None = None) -> NotebookSession:
        """The existing session for notebook_id; raises a structured error otherwise."""
        key = notebook_id or DEFAULT_NOTEBOOK_ID
        session = self._sessions.get(key)
        if session is not None:
            return session
        if notebook_id is None:
            raise fail(
                "not_connected",
                "No Colab connection yet — call open_colab_browser_connection first.",
            )
        raise fail(
            "unknown_notebook",
            f"Unknown notebook_id '{notebook_id}' — "
            "open it first with open_colab_browser_connection.",
            notebook_id=notebook_id,
        )

    async def get_or_create(self, notebook_id: str | None = None) -> NotebookSession:
        """The session for notebook_id, starting a new one (own WebSocket server) if needed."""
        key = notebook_id or DEFAULT_NOTEBOOK_ID
        async with self._create_lock:
            session = self._sessions.get(key)
            if session is None:
                session = NotebookSession(key)
                await session.start()
                self._sessions[key] = session
                logger.info(
                    "Created session '%s' (WebSocket port %d)", key, session.port
                )
        return session

    async def close(self, notebook_id: str | None = None) -> None:
        """Shut down and forget the session for notebook_id."""
        session = self.get(notebook_id)
        del self._sessions[session.notebook_id]
        await session.aclose()
        logger.info("Closed session '%s'", session.notebook_id)

    async def aclose(self) -> None:
        """Shut down every session."""
        for session in list(self._sessions.values()):
            await session.aclose()
        self._sessions.clear()
