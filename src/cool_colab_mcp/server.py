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

"""The root FastMCP server with its static tool surface.

Every tool is pre-registered at startup so all MCP clients see it immediately
(most clients ignore `notifications/tools/list_changed`). Tools called without
a live Colab connection return a structured not_connected error — never an
invisible tool, never a silent stub.
"""

import logging
import webbrowser
from functools import partial
from pathlib import Path
from typing import Any, Protocol

from fastmcp import FastMCP
from fastmcp.dependencies import CurrentContext
from fastmcp.server.context import Context
from fastmcp.tools.tool import ToolResult

from cool_colab_mcp.constants import (
    ADD_CODE_CELL,
    ADD_TEXT_CELL,
    DELETE_CELL,
    DEFAULT_CODE_CELL_INDEX,
    DEFAULT_CODE_LANGUAGE,
    DEFAULT_TEXT_CELL_INDEX,
    GET_CELLS,
    MOVE_CELL,
    PROXY_PORT_PARAM,
    PROXY_TOKEN_PARAM,
    RUN_CODE_CELL,
    SERVER_NAME,
    TAB_DEDUP_PARAM,
    UI_CONNECTION_TIMEOUT,
    UPDATE_CELL,
    COLAB,
    SCRATCH_PATH,
)
from cool_colab_mcp.errors import ToolFailed, fail
from cool_colab_mcp.registry.tools import register_registry_tools
from cool_colab_mcp.runtime.tools import register_runtime_tools
from cool_colab_mcp.sessions.manager import SessionManager
from cool_colab_mcp.sessions.session import NotebookSession, validate_notebook_url
from cool_colab_mcp.snapshots.tools import register_snapshot_tools
from cool_colab_mcp.transfer_tools import register_transfer_tools
from cool_colab_mcp.utils import json_tool_result

logger = logging.getLogger(__name__)


class BrowserController(Protocol):
    async def open_and_approve(
        self,
        notebook_id: str,
        connection_url: str,
        notebook_url: str,
        token: str,
        port: int,
    ) -> None: ...


def _status(session: NotebookSession, connected: bool, url: str | None) -> ToolResult:
    return json_tool_result(
        {
            "connected": connected,
            "notebook_id": session.notebook_id,
            "notebook_url": url,
        }
    )


async def open_connection(
    manager: SessionManager,
    notebook_url: str | None,
    notebook_id: str | None,
    ctx: Context,
    force_scratch: bool = False,
    browser: BrowserController | None = None,
) -> ToolResult:
    """The one open flow: resolve the notebook, open the browser tab, await the
    frontend connection with progress reports. Shared by
    open_colab_browser_connection and the registry's open_notebook; returns
    structured errors instead of raising."""
    try:
        if notebook_url is not None and not force_scratch:
            validate_notebook_url(notebook_url)
        session = await manager.get_or_create(notebook_id)
        if force_scratch:
            notebook_url = f"{COLAB}{SCRATCH_PATH}"
        if session.is_connected():
            if notebook_url is not None and notebook_url != session.active_notebook_url:
                raise fail(
                    "invalid_input",
                    f"Notebook '{session.notebook_id}' is already connected — "
                    "a live session cannot switch notebooks. Use another "
                    "notebook_id or close this session first.",
                    notebook_id=session.notebook_id,
                    active_notebook_url=session.active_notebook_url,
                    requested_notebook_url=notebook_url,
                )
            return _status(session, connected=True, url=session.active_notebook_url)
        if force_scratch:
            session.active_notebook_url = notebook_url
            session.set_output_cache_url(notebook_url)
            url = notebook_url
        else:
            url = session.resolve_notebook_url(notebook_url)
    except ToolFailed as failure:
        return failure.error.as_result()

    separator = "&" if "?" in url else "?"
    logger.info(
        "Opening notebook session '%s' on port %d",
        session.notebook_id,
        session.port,
    )
    connection_url = (
        f"{url}{separator}{TAB_DEDUP_PARAM}={session.port}"
        f"#{PROXY_TOKEN_PARAM}={session.token}&{PROXY_PORT_PARAM}={session.port}"
    )
    try:
        if browser is None:
            webbrowser.open_new(connection_url)
        else:
            await browser.open_and_approve(
                session.notebook_id,
                connection_url,
                url,
                session.token,
                session.port,
            )
    except ToolFailed as failure:
        return failure.error.as_result()
    await ctx.report_progress(
        progress=1, total=3, message=f"Opened Colab notebook: {url}"
    )
    await ctx.report_progress(
        progress=2,
        total=3,
        message=(
            "Waiting for user to connect in Colab - "
            f"will wait for {UI_CONNECTION_TIMEOUT:.0f}s"
        ),
    )
    connected = await session.await_connection(UI_CONNECTION_TIMEOUT)
    logger.info(
        "Session '%s' %s",
        session.notebook_id,
        "connected" if connected else "timed out waiting for the browser",
    )
    await ctx.report_progress(
        progress=3,
        total=3,
        message=(
            "The Colab UI is successfully connected!"
            if connected
            else "Timeout while waiting for the user to connect."
        ),
    )
    return _status(session, connected=connected, url=url)


def build_server(
    manager: SessionManager,
    oauth_config_path: Path | None = None,
    browser: BrowserController | None = None,
) -> FastMCP:
    """Create the root server and pre-register the whole tool surface."""
    mcp = FastMCP(
        name=SERVER_NAME,
        instructions=(
            "Connects to Google Colab notebooks in a browser and lets you edit and "
            "run them. Call open_colab_browser_connection first; pass notebook_id "
            "to work with several notebooks at once."
        ),
    )

    async def _forward(
        name: str, args: dict[str, Any], notebook_id: str | None
    ) -> ToolResult:
        try:
            return await manager.get(notebook_id).call_tool(name, args)
        except ToolFailed as failure:
            logger.warning(
                "Tool '%s' on notebook '%s' failed: %s",
                name,
                notebook_id or "default",
                failure.error.kind,
            )
            return failure.error.as_result()

    @mcp.tool
    async def open_colab_browser_connection(
        notebook_url: str | None = None,
        notebook_id: str | None = None,
        ctx: Context = CurrentContext(),
    ) -> ToolResult:
        """Open a Google Colab notebook in the browser and connect it to this server,
        unlocking the notebook editing tools.

        notebook_url picks the notebook to open and becomes this session's active
        notebook, so later reconnects return to it. Accepted forms:
        https://colab.research.google.com/drive/<FILE_ID> (keeps the live runtime
        across reconnects) and https://colab.research.google.com/github/<user>/<repo>/...
        Caveat for GitHub URLs: content loads from the remote branch, so local edits
        must be pushed to be visible. Without notebook_url the session's active
        notebook is reused, then the COLAB_MCP_NOTEBOOK_URL environment default,
        then a blank scratch notebook.

        notebook_id names the session to connect (default session when omitted);
        use distinct ids to keep several notebooks connected at once.

        A live session cannot switch notebooks: passing a different notebook_url
        while this session is connected returns an invalid_input error — use
        another notebook_id instead.

        Waits up to 60s for the user's browser tab to connect and reports progress.
        """
        return await open_connection(
            manager, notebook_url, notebook_id, ctx, browser=browser
        )

    @mcp.tool
    async def add_code_cell(
        code: str,
        cellIndex: int = DEFAULT_CODE_CELL_INDEX,
        language: str = DEFAULT_CODE_LANGUAGE,
        notebook_id: str | None = None,
    ) -> ToolResult:
        """Add a new code cell to the Colab notebook. Requires an active connection
        via open_colab_browser_connection; pass notebook_id to target a specific
        notebook session."""
        return await _forward(
            ADD_CODE_CELL,
            {"code": code, "cellIndex": cellIndex, "language": language},
            notebook_id,
        )

    @mcp.tool
    async def add_text_cell(
        content: str,
        cellIndex: int = DEFAULT_TEXT_CELL_INDEX,
        notebook_id: str | None = None,
    ) -> ToolResult:
        """Add a new text/markdown cell to the Colab notebook. Requires an active
        connection via open_colab_browser_connection; pass notebook_id to target a
        specific notebook session."""
        return await _forward(
            ADD_TEXT_CELL, {"content": content, "cellIndex": cellIndex}, notebook_id
        )

    @mcp.tool
    async def get_cells(notebook_id: str | None = None) -> ToolResult:
        """Read the notebook state: the cells with their ids, contents, and outputs.
        Requires an active connection via open_colab_browser_connection; pass
        notebook_id to target a specific notebook session."""
        return await _forward(GET_CELLS, {}, notebook_id)

    @mcp.tool
    async def run_code_cell(cellId: str, notebook_id: str | None = None) -> ToolResult:
        """Execute a code cell of the Colab notebook by cellId. Requires an active
        connection via open_colab_browser_connection; pass notebook_id to target a
        specific notebook session."""
        return await _forward(RUN_CODE_CELL, {"cellId": cellId}, notebook_id)

    @mcp.tool
    async def update_cell(
        cellId: str, content: str, notebook_id: str | None = None
    ) -> ToolResult:
        """Update the contents of an existing cell of the Colab notebook. Requires an
        active connection via open_colab_browser_connection; pass notebook_id to
        target a specific notebook session."""
        return await _forward(
            UPDATE_CELL, {"cellId": cellId, "content": content}, notebook_id
        )

    @mcp.tool
    async def delete_cell(cellId: str, notebook_id: str | None = None) -> ToolResult:
        """Delete a cell from the Colab notebook by cellId. Requires an active
        connection via open_colab_browser_connection; pass notebook_id to target a
        specific notebook session."""
        return await _forward(DELETE_CELL, {"cellId": cellId}, notebook_id)

    @mcp.tool
    async def move_cell(
        cellId: str, cellIndex: int, notebook_id: str | None = None
    ) -> ToolResult:
        """Move a cell of the Colab notebook to a new position by cellId and target
        index. Requires an active connection via open_colab_browser_connection; pass
        notebook_id to target a specific notebook session."""
        return await _forward(
            MOVE_CELL, {"cellId": cellId, "cellIndex": cellIndex}, notebook_id
        )

    register_registry_tools(mcp, manager, partial(open_connection, browser=browser))
    register_snapshot_tools(mcp, manager)
    register_transfer_tools(mcp, manager)
    register_runtime_tools(mcp, manager, oauth_config_path)

    return mcp
