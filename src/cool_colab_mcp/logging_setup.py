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

"""One logging configuration for the whole package.

Modules take their namespaced logger with ``logging.getLogger(__name__)``
(e.g. ``cool_colab_mcp.sessions.session``); every record carries timestamp,
level, logger name, and message.

SECURITY (plan.md §3/§14): never log tokens, cookies, or URLs carrying token
fragments — log the port, notebook_id, and event instead.
"""

import datetime
import logging
from pathlib import Path

from cool_colab_mcp.constants import (
    LOG_DATE_FORMAT,
    LOG_FILE_PREFIX,
    LOG_FILE_TIMESTAMP,
    LOG_FORMAT,
)

logger = logging.getLogger(__name__)


def init_logging(log_dir: str, verbose: bool = False) -> Path:
    """Log to a timestamped file in log_dir; DEBUG when verbose, INFO otherwise.

    Files only — stdout stays clean for the MCP stdio transport.
    """
    timestamp = datetime.datetime.now().strftime(LOG_FILE_TIMESTAMP)
    log_file = Path(log_dir) / f"{LOG_FILE_PREFIX}.{timestamp}.log"
    handler = logging.FileHandler(log_file)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.info("logging to %s", log_file)
    return log_file
