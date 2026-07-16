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

"""NotebookSession — one complete, independent connection to a Colab notebook (plan.md §6)."""

import asyncio
import contextlib
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from typing import Any
from urllib.parse import urlsplit

from fastmcp import Client
from fastmcp.client.client import CallToolResult
from fastmcp.client.transports import ClientTransport
from fastmcp.tools.tool import ToolResult
from mcp.client.session import ClientSession
from mcp.types import TextContent

from cool_colab_mcp.constants import (
    ADD_CODE_CELL,
    DEFAULT_CODE_CELL_INDEX,
    DEFAULT_CODE_LANGUAGE,
    CELL_ID_KEYS,
    COLAB,
    DRIVE_PATH_PREFIX,
    GITHUB_PATH_PREFIX,
    NOTEBOOK_URL_ENV,
    RUN_CODE_CELL,
    SCRATCH_PATH,
    UI_CONNECTION_TIMEOUT,
)
from cool_colab_mcp.errors import ToolFailed, fail
from cool_colab_mcp.sessions.websocket_server import ColabWebSocketServer

logger = logging.getLogger(__name__)


def validate_notebook_url(url: str) -> str:
    """Accept Drive and GitHub notebook URLs on the Colab host; reject everything else."""
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.netloc != urlsplit(COLAB).netloc
        or not parts.path.startswith((DRIVE_PATH_PREFIX, GITHUB_PATH_PREFIX))
    ):
        raise fail(
            "invalid_input",
            f"notebook_url must look like {COLAB}{DRIVE_PATH_PREFIX}<FILE_ID> "
            f"or {COLAB}{GITHUB_PATH_PREFIX}<user>/<repo>/...",
            notebook_url=url,
        )
    return url


class ColabTransport(ClientTransport):
    """fastmcp client transport speaking over a ColabWebSocketServer's streams."""

    def __init__(self, wss: ColabWebSocketServer):
        self.wss = wss

    @contextlib.asynccontextmanager
    async def connect_session(self, **session_kwargs) -> AsyncIterator[ClientSession]:
        async with ClientSession(
            self.wss.read_stream, self.wss.write_stream, **session_kwargs
        ) as session:
            yield session

    def __repr__(self) -> str:
        return "<ColabSessionProxyTransport>"


class ColabProxyClient:
    """Owns the MCP client attached to one Colab browser tab."""

    def __init__(self, wss: ColabWebSocketServer):
        self.wss = wss
        self.proxy_mcp_client: Client | None = None
        self._exit_stack = AsyncExitStack()
        self._start_task: asyncio.Task[None] | None = None

    def is_connected(self) -> bool:
        return self.wss.connection_live.is_set() and self.proxy_mcp_client is not None

    async def await_connection(self, timeout: float) -> bool:
        """Wait until the frontend is connected and the client is initialized, or time out."""
        if self._start_task is None:
            return False
        with contextlib.suppress(asyncio.TimeoutError):
            # Shield the initialization task: a timeout must not kill the pending
            # client startup, or a later browser connection could never complete.
            await asyncio.wait_for(
                asyncio.gather(
                    self.wss.connection_live.wait(), asyncio.shield(self._start_task)
                ),
                timeout=timeout,
            )
        return self.is_connected()

    async def call_tool(self, name: str, args: dict[str, Any]) -> CallToolResult:
        """Forward one tool call to the Colab frontend. The mockable test boundary."""
        assert self.proxy_mcp_client is not None
        return await self.proxy_mcp_client.call_tool(name, args)

    async def _start_proxy_client(self) -> None:
        # blocks until a websocket connection is made successfully
        self.proxy_mcp_client = await self._exit_stack.enter_async_context(
            Client(ColabTransport(self.wss))
        )

    async def __aenter__(self) -> "ColabProxyClient":
        self._start_task = asyncio.create_task(self._start_proxy_client())
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._start_task:
            self._start_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._start_task
        await self._exit_stack.aclose()


class NotebookSession:
    """One notebook's complete session: own WebSocket server (token/port), proxy
    client, operation lock, and active-notebook state."""

    def __init__(self, notebook_id: str):
        self.notebook_id = notebook_id
        self.lock = asyncio.Lock()
        self.active_notebook_url: str | None = None
        self.wss: ColabWebSocketServer | None = None
        self.proxy_client: ColabProxyClient | None = None
        self.cell_outputs: dict[str, list[Any]] = {}
        self._exit_stack = AsyncExitStack()

    async def start(self) -> None:
        self.wss = await self._exit_stack.enter_async_context(ColabWebSocketServer())
        self.proxy_client = await self._exit_stack.enter_async_context(
            ColabProxyClient(self.wss)
        )

    async def aclose(self) -> None:
        await self._exit_stack.aclose()

    @property
    def token(self) -> str:
        assert self.wss is not None
        return self.wss.token

    @property
    def port(self) -> int:
        assert self.wss is not None
        return self.wss.port

    def is_connected(self) -> bool:
        return self.proxy_client is not None and self.proxy_client.is_connected()

    async def await_connection(self, timeout: float = UI_CONNECTION_TIMEOUT) -> bool:
        return (
            self.proxy_client is not None
            and await self.proxy_client.await_connection(timeout)
        )

    def resolve_notebook_url(self, notebook_url: str | None) -> str:
        """Pick the notebook to open: explicit URL → active notebook → env pin → scratch.

        An explicit URL becomes the session's active notebook, so reconnects return to it.
        """
        if notebook_url is not None:
            self.active_notebook_url = validate_notebook_url(notebook_url)
        if self.active_notebook_url:
            return self.active_notebook_url
        return os.environ.get(NOTEBOOK_URL_ENV) or f"{COLAB}{SCRATCH_PATH}"

    async def call_tool(self, name: str, args: dict[str, Any]) -> ToolResult:
        """Forward a notebook tool call to the frontend, serialized by the session lock."""
        async with self.lock:
            raw = await self._call(name, args)
            self._remember_cell_outputs(name, args, raw)
        return ToolResult(
            content=raw.content, structured_content=raw.structured_content
        )

    async def run_code(self, code: str) -> dict[str, Any]:
        """The shared execution channel: add a code cell, run it, return the parsed result.

        Uploads, snapshots, and runtime checks build on this.
        """
        async with self.lock:
            added = await self._call(
                ADD_CODE_CELL,
                {
                    "code": code,
                    "cellIndex": DEFAULT_CODE_CELL_INDEX,
                    "language": DEFAULT_CODE_LANGUAGE,
                },
            )
            cell_id = _extract_cell_id(added)
            args = {"cellId": cell_id}
            ran = await self._call(RUN_CODE_CELL, args)
            self._remember_cell_outputs(RUN_CODE_CELL, args, ran)
        if ran.structured_content is not None:
            return ran.structured_content
        return {"text": _text_of(ran)}

    def merge_cached_outputs(self, document: dict[str, Any]) -> dict[str, Any]:
        """Restore outputs returned by run_code_cell when get_cells omits them."""
        for cell in document["cells"]:
            cell_id = cell.get("id")
            if cell.get("cell_type") == "code" and cell_id in self.cell_outputs:
                cell["outputs"] = self.cell_outputs[cell_id]
        return document

    def _remember_cell_outputs(
        self, name: str, args: dict[str, Any], result: CallToolResult
    ) -> None:
        if name != RUN_CODE_CELL or not isinstance(result.structured_content, dict):
            return
        cell_id = args.get("cellId")
        outputs = result.structured_content.get("outputs")
        if isinstance(cell_id, str) and isinstance(outputs, list):
            self.cell_outputs[cell_id] = outputs

    async def _call(self, name: str, args: dict[str, Any]) -> CallToolResult:
        if not self.is_connected():
            raise fail(
                "not_connected",
                f"Notebook '{self.notebook_id}' has no live Colab connection — "
                "call open_colab_browser_connection first.",
                notebook_id=self.notebook_id,
            )
        assert self.proxy_client is not None
        try:
            return await self.proxy_client.call_tool(
                name, {k: v for k, v in args.items() if v is not None}
            )
        except ToolFailed:
            raise
        except Exception as exc:
            logger.exception(
                "Forwarding tool '%s' to notebook '%s' failed", name, self.notebook_id
            )
            # A WebSocket drop mid-call surfaces as an unstructured exception
            # from the read stream; translate it into the not_connected
            # contract. Errors while the connection is still live are real
            # bugs and propagate unchanged.
            if self.is_connected():
                raise
            raise fail(
                "not_connected",
                f"Connection to notebook '{self.notebook_id}' was lost during "
                f"'{name}' — call open_colab_browser_connection to reconnect.",
                notebook_id=self.notebook_id,
            ) from exc


def _text_of(result: CallToolResult) -> str:
    return "\n".join(
        block.text for block in result.content if isinstance(block, TextContent)
    )


def _cell_id_in(data: Any) -> str | None:
    """Read the cell id from the verified Colab add_code_cell response."""
    if not isinstance(data, dict):
        return None
    for key in CELL_ID_KEYS:
        if isinstance(data.get(key), str):
            return data[key]
    return None


def _extract_cell_id(result: CallToolResult) -> str:
    """Find the new cell's id in an add_code_cell result (structured or JSON text)."""
    cell_id = _cell_id_in(result.structured_content)
    if cell_id is None:
        with contextlib.suppress(ValueError):
            cell_id = _cell_id_in(json.loads(_text_of(result)))
    if cell_id is None:
        raise fail(
            "protocol_error",
            "add_code_cell returned no cell id — the Colab frontend response "
            "shape may have changed.",
        )
    return cell_id
