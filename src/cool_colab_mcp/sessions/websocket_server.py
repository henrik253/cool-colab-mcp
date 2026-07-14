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

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
import asyncio
import logging
import mcp.types as types
from mcp.shared.message import SessionMessage
from pydantic_core import ValidationError
import secrets
import socket
import websockets
from websockets.asyncio.server import ServerConnection
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response
from websockets.typing import Subprotocol

from cool_colab_mcp import process_registry
from cool_colab_mcp.constants import (
    COLAB,
    COLAB_ALT_DOMAIN,
    IPV4_LOOPBACK,
    PORT_BIND_ATTEMPTS,
    WEBSOCKET_HOST,
)


def _probe_free_port() -> int:
    """Find a currently free loopback port to bind both address families on."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((IPV4_LOOPBACK, 0))
        return sock.getsockname()[1]


logger = logging.getLogger(__name__)


class ColabWebSocketServer:
    """
    A WebSocket server designed to accept a single connection specifically
    from a Google Colab session (colab.google.com).
    """

    def __init__(self, host: str = WEBSOCKET_HOST) -> None:
        self.host = host
        self.port = 0
        self.connection_lock = asyncio.Lock()
        self.connection_live = asyncio.Event()
        self.allowed_origins = [COLAB, COLAB_ALT_DOMAIN]
        self._server: websockets.Server | None = None

        self.read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
        self._read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]
        self.write_stream: MemoryObjectSendStream[SessionMessage]
        self._write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

        self._read_stream_writer, self.read_stream = anyio.create_memory_object_stream(
            0
        )
        self.write_stream, self._write_stream_reader = (
            anyio.create_memory_object_stream(0)
        )
        self.token = secrets.token_urlsafe(16)

    async def _read_from_socket(self, websocket):
        """Listens to the socket and puts messages into the read stream."""
        async for msg in websocket:
            try:
                client_message = types.JSONRPCMessage.model_validate_json(msg)
            except ValidationError as exc:
                await self._read_stream_writer.send(exc)
                continue
            await self._read_stream_writer.send(SessionMessage(client_message))

    async def _write_to_socket(self, websocket):
        """Reads from the write stream and sends over the socket."""
        try:
            while True:
                # Wait for a message from the application
                msg = await self._write_stream_reader.receive()

                try:
                    json_obj = msg.message.model_dump_json(
                        by_alias=True, exclude_none=True
                    )
                    await websocket.send(json_obj)
                except ConnectionClosed:
                    break
        except (anyio.ClosedResourceError, anyio.EndOfStream):
            # server closed write stream
            pass

    def _pna_headers(self, origin: str | None) -> list[tuple[str, str]]:
        """CORS headers for Chrome's Private Network Access (PNA).

        A public origin (colab.research.google.com) opening a WebSocket to
        localhost is a "private network request": Chrome stalls the upgrade
        until the server answers `Access-Control-Allow-Private-Network: true`
        — on the OPTIONS preflight AND on the upgrade response itself.
        Without it the tab shows "Disconnected from the local Colab MCP
        server". Ported from SebastianGilPinzon/colab-mcp (Apache 2.0).
        """
        return [
            (
                "Access-Control-Allow-Origin",
                origin if origin in self.allowed_origins else COLAB,
            ),
            ("Access-Control-Allow-Methods", "GET, OPTIONS"),
            (
                "Access-Control-Allow-Headers",
                "authorization,content-type,sec-websocket-protocol,"
                "sec-websocket-key,sec-websocket-version,sec-websocket-extensions",
            ),
            ("Access-Control-Allow-Private-Network", "true"),
            ("Access-Control-Allow-Credentials", "true"),
            ("Access-Control-Max-Age", "86400"),
        ]

    def _add_pna_headers(
        self, websocket: ServerConnection, request: Request, response: Response
    ) -> Response:
        """Chrome re-checks PNA on the actual upgrade response (101), not just
        the preflight — without these headers there too, the socket is
        terminated right after connecting."""
        for name, value in self._pna_headers(request.headers.get("Origin")):
            response.headers[name] = value
        return response

    def _validate_authorization(self, websocket: ServerConnection, request: Request):
        if request.headers.get("Upgrade", "").lower() != "websocket":
            # A PNA preflight arrives before the WebSocket upgrade and must be
            # answered directly. Note: the websockets library rejects non-GET
            # methods before process_request runs, so a literal OPTIONS never
            # reaches us — this answers any parseable non-upgrade request,
            # while the upgrade response below carries the decisive headers.
            return Response(
                204,
                "No Content",
                Headers(self._pna_headers(request.headers.get("Origin"))),
            )
        if request.path.find(f"access_token={self.token}") != -1:
            return None
        try:
            headers: Headers = request.headers
            auth_header = headers.get("Authorization")
            if not auth_header:
                return Response(401, "Missing authorization", Headers([]))
            scheme, token = auth_header.split(None, 1)
            if scheme.lower() != "bearer":
                return Response(400, "Invalid authorization header", Headers([]))
        except ValueError:
            return Response(400, "Invalid header format", Headers([]))
        if token == self.token:
            return None
        return Response(403, "Bad authorization token", Headers([]))

    async def _connection_handler(self, websocket: ServerConnection):
        """
        Handles incoming websocket connections.
        Validates Origin and ensures single-client exclusivity.
        """
        if self.connection_lock.locked():
            logger.warning(
                f"Connection rejected: {websocket.remote_address}. A client is already connected"
            )
            await websocket.close(code=1013, reason="Server is busy")
            return

        async with self.connection_lock:
            try:
                self.connection_live.set()
                logger.info("Colab frontend connected on port %d", self.port)

                reading_task = asyncio.create_task(self._read_from_socket(websocket))
                writing_task = asyncio.create_task(self._write_to_socket(websocket))
                _, pending = await asyncio.wait(
                    [reading_task, writing_task], return_when=asyncio.FIRST_COMPLETED
                )

                for task in pending:
                    task.cancel()

            except websockets.exceptions.ConnectionClosed as e:
                logger.info(f"Connection closed: {e.code} - {e.reason}")
                await self._read_stream_writer.send(
                    Exception("Colab Frontend disconnected")
                )
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
            finally:
                self.connection_live.clear()
                logger.info("Colab frontend disconnected from port %d", self.port)

    async def __aenter__(self):
        # Dual-stack bind on ONE port. With host="localhost" and port=0, IPv4
        # and IPv6 each get a DIFFERENT ephemeral port; we would report one,
        # and whenever the browser resolves localhost to the other family the
        # tab hits a portless family and shows "Disconnected from the local
        # Colab MCP server". Probing a free port and binding every resolved
        # loopback address on that fixed port keeps the reported port
        # reachable over both families (fix from SebastianGilPinzon/colab-mcp,
        # adapted from its IPv4-only bind to a true dual-stack one).
        for attempt in range(PORT_BIND_ATTEMPTS):
            port = _probe_free_port()
            try:
                self._server = await websockets.serve(
                    self._connection_handler,
                    host=self.host,
                    port=port,
                    subprotocols=[Subprotocol("mcp")],
                    origins=self.allowed_origins,
                    process_request=self._validate_authorization,
                    process_response=self._add_pna_headers,
                )
                break
            except OSError:
                if attempt == PORT_BIND_ATTEMPTS - 1:
                    raise
        self.port = port
        try:
            process_registry.register(port=self.port, host=self.host)
        except Exception as exc:  # registry trouble must never block serving
            logger.warning("Could not record server in process registry: %s", exc)
        logger.info(f"Starting WebSocket server on ws://{self.host}:{self.port}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        logger.info("Closing WebSocket server on port %d", self.port)
        if self._server:
            self._server.close()
            self.write_stream.close()
            self.read_stream.close()
            await self._server.wait_closed()
            try:
                process_registry.unregister(self.port)
            except Exception as exc:
                logger.warning("Could not unregister server: %s", exc)
