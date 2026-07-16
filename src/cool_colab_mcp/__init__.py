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
import sys
import tempfile
from pathlib import Path

from cool_colab_mcp import doctor, process_registry
from cool_colab_mcp.constants import LOG_DIR_PREFIX
from cool_colab_mcp.logging_setup import init_logging
from cool_colab_mcp.server import build_server
from cool_colab_mcp.sessions.manager import SessionManager


def parse_args(v: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Cool Colab MCP is an MCP server that turns Google Colab notebooks "
            "into persistent, multi-session workspaces."
        )
    )
    parser.add_argument(
        "--client-oauth-config",
        type=Path,
        help="OAuth Desktop-app client-secrets JSON for runtime switching",
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
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="log at DEBUG level instead of INFO",
    )
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser(
        "doctor",
        help="check the local environment (versions, directories, port binding) "
        "and report each item as pass/fail",
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


async def main_async(args: argparse.Namespace | None = None) -> None:
    args = args or parse_args(sys.argv[1:])
    init_logging(args.log, verbose=args.verbose)
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
        await build_server(manager, args.client_oauth_config).run_async()
    finally:
        await manager.aclose()


def main() -> None:
    args = parse_args(sys.argv[1:])
    if args.list_running:
        print_running()
        return
    if args.kill_stale:
        kill_stale()
        return
    if args.command == "doctor":
        sys.exit(doctor.main(args.log))
    asyncio.run(main_async(args))
