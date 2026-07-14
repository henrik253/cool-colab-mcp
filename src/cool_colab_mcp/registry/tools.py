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

"""The notebook-registry MCP tools, attached to the root server (plan.md §4)."""

from collections.abc import Awaitable, Callable

from fastmcp import FastMCP
from fastmcp.dependencies import CurrentContext
from fastmcp.server.context import Context
from fastmcp.tools.tool import ToolResult

from cool_colab_mcp.errors import ToolFailed
from cool_colab_mcp.registry.records import NotebookRecord, NotebookRegistry
from cool_colab_mcp.sessions.manager import SessionManager
from cool_colab_mcp.utils import json_tool_result

# The shared open flow (server.open_connection), injected to avoid a circular import
OpenConnection = Callable[
    [SessionManager, str | None, str | None, Context], Awaitable[ToolResult]
]


def register_registry_tools(
    mcp: FastMCP, manager: SessionManager, open_connection: OpenConnection
) -> None:
    """Attach the registry tool surface to the root server."""
    registry = NotebookRegistry()

    def _record_payload(record: NotebookRecord) -> dict:
        return record.model_dump(exclude_none=True)

    @mcp.tool
    async def register_notebook(
        notebook_id: str,
        name: str,
        url: str,
        preferred_runtime: str | None = None,
    ) -> ToolResult:
        """Register a Colab notebook under a memorable notebook_id so open_notebook
        can reopen it later — the registry survives server restarts. Re-registering
        an existing notebook_id updates its record. url must be a Colab Drive or
        GitHub notebook URL; preferred_runtime (e.g. "cpu", "gpu") is stored for
        later use and has no effect yet."""
        try:
            record = NotebookRecord(
                notebook_id=notebook_id,
                name=name,
                url=url,
                preferred_runtime=preferred_runtime,
            )
            registry.register(record)
        except ToolFailed as failure:
            return failure.error.as_result()
        return json_tool_result({"notebook": _record_payload(record)})

    @mcp.tool
    async def list_notebooks() -> ToolResult:
        """List every registered notebook with its notebook_id, name, url, and
        preferred_runtime."""
        try:
            records = registry.list()
        except ToolFailed as failure:
            return failure.error.as_result()
        return json_tool_result(
            {"notebooks": [_record_payload(record) for record in records]}
        )

    @mcp.tool
    async def remove_notebook(notebook_id: str) -> ToolResult:
        """Remove a notebook from the registry. Any live session stays untouched;
        close it with close_notebook if needed."""
        try:
            registry.remove(notebook_id)
        except ToolFailed as failure:
            return failure.error.as_result()
        return json_tool_result({"removed": notebook_id})

    @mcp.tool
    async def get_notebook_status(notebook_id: str) -> ToolResult:
        """The registered record plus live-session state for a notebook: whether a
        session exists, whether its browser tab is connected, and the URL the
        session actually has open."""
        try:
            record = registry.get(notebook_id)
        except ToolFailed as failure:
            return failure.error.as_result()
        try:
            session = manager.get(notebook_id)
            state = {
                "session_exists": True,
                "connected": session.is_connected(),
                "active_notebook_url": session.active_notebook_url,
            }
        except ToolFailed:
            state = {
                "session_exists": False,
                "connected": False,
                "active_notebook_url": None,
            }
        return json_tool_result({"notebook": _record_payload(record), **state})

    @mcp.tool
    async def open_notebook(
        notebook_id: str, ctx: Context = CurrentContext()
    ) -> ToolResult:
        """Open a registered notebook in the browser and connect it to this server,
        exactly like open_colab_browser_connection with the registered URL. The
        registry notebook_id names the session, so notebook tools can target it.
        Waits up to 60s for the user's browser tab to connect and reports progress."""
        try:
            record = registry.get(notebook_id)
        except ToolFailed as failure:
            return failure.error.as_result()
        return await open_connection(manager, record.url, record.notebook_id, ctx)

    @mcp.tool
    async def close_notebook(notebook_id: str) -> ToolResult:
        """Close a registered notebook's live session (its WebSocket server and
        browser connection). Idempotent: closing a notebook that has no live
        session succeeds with session_existed=false. The registry record is
        kept, so open_notebook can reopen it later."""
        try:
            registry.get(notebook_id)
        except ToolFailed as failure:
            return failure.error.as_result()
        try:
            await manager.close(notebook_id)
            session_existed = True
        except ToolFailed:
            session_existed = False
        return json_tool_result(
            {"closed": notebook_id, "session_existed": session_existed}
        )
