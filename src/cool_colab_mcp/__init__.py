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

"""Cool Colab MCP — persistent, multi-notebook Colab workspaces for AI agents."""

import argparse
import asyncio
import datetime
import logging
import sys
import tempfile

from fastmcp.utilities import logging as fastmcp_logger

from cool_colab_mcp import process_registry
from cool_colab_mcp.constants import LOG_DIR_PREFIX, LOG_FILE_PREFIX, LOGGER_NAME
from cool_colab_mcp.server import build_server
from cool_colab_mcp.sessions.manager import SessionManager


def init_logger(logdir: str) -> None:
    log_filename = datetime.datetime.now().strftime(
        f"{logdir}/{LOG_FILE_PREFIX}.%Y-%m-%d_%H-%M-%S.log"
    )
    logging.basicConfig(
        format="%(asctime)s %(levelname)s:%(message)s",
        datefmt="%m/%d/%Y %I:%M:%S %p",
        filename=log_filename,
        level=logging.INFO,  # Set the minimum logging level to capture
    )
    fastmcp_logger.get_logger(LOGGER_NAME).info("logging to %s", log_filename)


def parse_args(v: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Cool Colab MCP is an MCP server that turns Google Colab notebooks "
            "into persistent, multi-session workspaces."
        )
    )
    parser.add_argument(
        "-l",
        "--log",
        help="if set, use this directory as a location for logfiles (if unset, "
        f"will log to {tempfile.gettempdir()}/{LOG_DIR_PREFIX}*/)",
        action="store",
        default=tempfile.mkdtemp(prefix=LOG_DIR_PREFIX),
    )
    parser.add_argument(
        "--list-running",
        help="list running cool-colab-mcp servers from the process registry and exit",
        action="store_true",
    )
    parser.add_argument(
        "--kill-stale",
        help="terminate cool-colab-mcp servers left over from other processes "
        "and exit (fixes stale browser tabs pointing at dead ports)",
        action="store_true",
    )
    return parser.parse_args(v)


def print_running() -> None:
    entries = process_registry.list_running()
    if not entries:
        print("No running cool-colab-mcp servers registered.")
        return
    for entry in entries:
        started = datetime.datetime.fromtimestamp(entry.started_at).isoformat(
            sep=" ", timespec="seconds"
        )
        print(f"pid={entry.pid} port={entry.port} host={entry.host} started={started}")


def kill_stale() -> None:
    removed = process_registry.kill_stale()
    if not removed:
        print("No stale cool-colab-mcp servers found.")
        return
    for entry in removed:
        print(f"removed pid={entry.pid} port={entry.port}")


async def main_async() -> None:
    args = parse_args(sys.argv[1:])
    init_logger(args.log)

    if args.list_running:
        print_running()
        return
    if args.kill_stale:
        kill_stale()
        return

    # Entries from crashed runs would otherwise accumulate forever.
    process_registry.prune_dead()

    manager = SessionManager()
    try:
        await build_server(manager).run_async()
    finally:
        await manager.aclose()


def main() -> None:
    asyncio.run(main_async())
