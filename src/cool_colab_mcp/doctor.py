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

"""`cool-colab-mcp doctor` — local environment health checks.

Each check is one small function returning a CheckResult; future features
(auth state, stale servers) append their own functions to run_checks.
"""

import importlib.metadata
import os
import socket
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

from cool_colab_mcp import process_registry, storage
from cool_colab_mcp.constants import (
    DIST_NAME,
    HOME_ENV,
    MIN_PYTHON,
    NOTEBOOK_URL_ENV,
    WEBSOCKET_HOST,
)


class CheckResult(NamedTuple):
    name: str
    ok: bool
    hint: str


def _dir_writable(path: Path) -> bool:
    """Probe by creating the directory and a temporary file inside it."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=path):
            return True
    except OSError:
        return False


def check_python_version() -> CheckResult:
    wanted = ".".join(map(str, MIN_PYTHON))
    found = ".".join(map(str, sys.version_info[:3]))
    ok = tuple(sys.version_info[:2]) >= MIN_PYTHON
    hint = (
        f"found {found}"
        if ok
        else f"found {found} — install Python {wanted}+ (`uv sync` manages it)"
    )
    return CheckResult(f"Python >= {wanted}", ok, hint)


def check_package_version() -> CheckResult:
    try:
        version = importlib.metadata.version(DIST_NAME)
        return CheckResult(f"{DIST_NAME} installed", True, f"version {version}")
    except importlib.metadata.PackageNotFoundError:
        return CheckResult(
            f"{DIST_NAME} installed",
            False,
            "package metadata not found — run `uv sync --group dev`",
        )


def check_storage_dir() -> CheckResult:
    path = storage.base_dir()
    ok = _dir_writable(path)
    return CheckResult(
        f"storage dir {path} writable",
        ok,
        "" if ok else f"set {HOME_ENV} to a writable directory",
    )


def check_log_dir(log_dir: str) -> CheckResult:
    ok = _dir_writable(Path(log_dir))
    return CheckResult(
        f"log dir {log_dir} writable",
        ok,
        "" if ok else "pass --log <dir> pointing at a writable directory",
    )


def check_websocket_port() -> CheckResult:
    try:
        with socket.socket() as sock:
            sock.bind((WEBSOCKET_HOST, 0))
        return CheckResult("WebSocket server can bind a port", True, "")
    except OSError as exc:
        return CheckResult(
            "WebSocket server can bind a port",
            False,
            f"binding on {WEBSOCKET_HOST} failed ({exc}) — "
            "check firewall or sandbox settings",
        )


def check_notebook_env_pin() -> CheckResult:
    """Informational: report whether the legacy notebook pin is set."""
    hint = (
        "set — connections without notebook_url open the pinned notebook"
        if os.environ.get(NOTEBOOK_URL_ENV)
        else "not set — connections without notebook_url fall back to "
        "the active or scratch notebook"
    )
    return CheckResult(f"{NOTEBOOK_URL_ENV} pin", True, hint)


def check_stale_servers() -> CheckResult:
    """Report registered servers that can leave browser tabs on old ports."""
    try:
        entries = process_registry.list_running()
    except Exception as exc:
        return CheckResult(
            "No stale servers registered",
            False,
            f"process registry could not be read ({exc}) — check {HOME_ENV}",
        )
    if entries:
        return CheckResult(
            "No stale servers registered",
            False,
            f"found {len(entries)} registered server(s) — run "
            "`cool-colab-mcp --kill-stale` if they are no longer needed",
        )
    return CheckResult("No stale servers registered", True, "")


def run_checks(log_dir: str) -> list[CheckResult]:
    return [
        check_python_version(),
        check_package_version(),
        check_storage_dir(),
        check_log_dir(log_dir),
        check_websocket_port(),
        check_notebook_env_pin(),
        check_stale_servers(),
    ]


def main(log_dir: str) -> int:
    """Print every check as pass/fail with its hint; 0 when all pass, 1 otherwise."""
    results = run_checks(log_dir)
    for name, ok, hint in results:
        line = f"[{'PASS' if ok else 'FAIL'}] {name}"
        if hint:
            line += f" — {hint}"
        print(line)
    return 0 if all(result.ok for result in results) else 1
