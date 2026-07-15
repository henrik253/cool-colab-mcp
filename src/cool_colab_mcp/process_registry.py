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

"""Stale-server process registry.

A Colab tab connects to the ws://localhost:<port> named in its URL fragment.
When that server dies uncleanly, the browser keeps a tab pointing at a dead
port and shows "Disconnected from the local Colab MCP server". The registry
records every live WebSocket server so stale ones can be pruned on startup,
listed (`--list-running`), and terminated (`--kill-stale`).

Ported from SebastianGilPinzon/colab-mcp (Apache 2.0), adapted to the atomic
JSON store in storage.py and to one entry per WebSocket server (a process
hosts one server per notebook session).
"""

import contextlib
import logging
import os
import signal
import time

from pydantic import BaseModel

from cool_colab_mcp import storage
from cool_colab_mcp.constants import (
    KILL_GRACE_TIMEOUT,
    KILL_POLL_INTERVAL,
    PROCESS_REGISTRY_STORE,
)


class ServerEntry(BaseModel):
    """One running WebSocket server: the address a Colab tab may point at."""

    pid: int
    port: int
    host: str
    started_at: float  # epoch seconds


def is_alive(pid: int) -> bool:
    """Liveness check via signal 0; a foreign-owned process still counts as alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def register(port: int, host: str) -> ServerEntry:
    """Record this process's server at `port`, pruning dead entries on the way."""
    entry = ServerEntry(pid=os.getpid(), port=port, host=host, started_at=time.time())
    with storage.lock(PROCESS_REGISTRY_STORE):
        entries = {key: e for key, e in _load().items() if is_alive(e.pid)}
        entries[_key(entry.pid, entry.port)] = entry
        _save(entries)
    return entry


def unregister(port: int) -> None:
    """Drop this process's entry for `port` (clean shutdown)."""
    with storage.lock(PROCESS_REGISTRY_STORE):
        entries = _load()
        if entries.pop(_key(os.getpid(), port), None) is not None:
            _save(entries)


def prune_dead() -> int:
    """Remove entries whose pid is gone; returns how many were pruned."""
    with storage.lock(PROCESS_REGISTRY_STORE):
        entries = _load()
        alive = {key: e for key, e in entries.items() if is_alive(e.pid)}
        if len(alive) != len(entries):
            _save(alive)
    return len(entries) - len(alive)


def list_running() -> list[ServerEntry]:
    """Every registered server whose process is still alive."""
    return [e for e in _load().values() if is_alive(e.pid)]


def kill_stale() -> list[ServerEntry]:
    """Remove dead entries and terminate servers of other processes.

    Never signals the calling process. Returns the entries removed.
    """
    with storage.lock(PROCESS_REGISTRY_STORE):
        removed: list[ServerEntry] = []
        kept: dict[str, ServerEntry] = {}
        for key, entry in _load().items():
            if not is_alive(entry.pid):
                removed.append(entry)
            elif entry.pid != os.getpid() and _terminate(entry.pid):
                removed.append(entry)
            else:
                kept[key] = entry
        _save(kept)
    return removed


def _key(pid: int, port: int) -> str:
    return f"{pid}:{port}"


def _load() -> dict[str, ServerEntry]:
    try:
        raw = storage.load(PROCESS_REGISTRY_STORE)
        return {key: ServerEntry(**value) for key, value in raw.items()}
    except (ValueError, TypeError) as exc:  # corrupt registry: start fresh
        logging.warning(f"Ignoring corrupt process registry: {exc}")
        return {}


def _save(entries: dict[str, ServerEntry]) -> None:
    storage.save(
        PROCESS_REGISTRY_STORE,
        {key: entry.model_dump() for key, entry in entries.items()},
    )


def _terminate(pid: int) -> bool:
    """SIGTERM, escalate to SIGKILL; True once the process is gone."""
    for sig in (signal.SIGTERM, getattr(signal, "SIGKILL", signal.SIGTERM)):
        if not is_alive(pid):
            return True
        with contextlib.suppress(OSError):
            os.kill(pid, sig)
        deadline = time.monotonic() + KILL_GRACE_TIMEOUT
        while time.monotonic() < deadline:
            if not is_alive(pid):
                return True
            time.sleep(KILL_POLL_INTERVAL)
    return not is_alive(pid)
