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
    return parser.parse_args(v)


async def main_async() -> None:
    args = parse_args(sys.argv[1:])
    init_logger(args.log)

    manager = SessionManager()
    try:
        await build_server(manager).run_async()
    finally:
        await manager.aclose()


def main() -> None:
    asyncio.run(main_async())
