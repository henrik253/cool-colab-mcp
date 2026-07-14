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

"""All constants, URLs, paths, and magic values used across the package."""

# Colab URLs and notebook paths
COLAB = "https://colab.research.google.com"
COLAB_ALT_DOMAIN = "https://colab.google.com"
SCRATCH_PATH = "/notebooks/empty.ipynb"
DRIVE_PATH_PREFIX = "/drive/"
GITHUB_PATH_PREFIX = "/github/"

# URL fragment parameters the Colab frontend reads to attach to our WebSocket server
PROXY_TOKEN_PARAM = "mcpProxyToken"
PROXY_PORT_PARAM = "mcpProxyPort"
# Query param carrying the server port so Chrome cannot dedupe onto a stale tab
# whose fragment points at a dead server (SebastianGilPinzon/colab-mcp fix)
TAB_DEDUP_PARAM = "p"

# WebSocket server binding
WEBSOCKET_HOST = "localhost"
IPV4_LOOPBACK = "127.0.0.1"
PORT_BIND_ATTEMPTS = 5

# Timeouts
UI_CONNECTION_TIMEOUT = 60.0  # secs
KILL_GRACE_TIMEOUT = 3.0  # secs to wait after signalling a stale server
KILL_POLL_INTERVAL = 0.1  # secs between liveness polls while killing

# Sessions
DEFAULT_NOTEBOOK_ID = "default"

# Environment variables
NOTEBOOK_URL_ENV = "COLAB_MCP_NOTEBOOK_URL"  # legacy notebook pin (headless callers)
HOME_ENV = "COOL_COLAB_MCP_HOME"

# Persistent local storage
DEFAULT_HOME_DIR = "~/.cool-colab-mcp"
STORAGE_SUFFIX = ".json"
STORAGE_LOCK_SUFFIX = ".lock"
PROCESS_REGISTRY_STORE = "servers"  # storage.py store of running WebSocket servers

# Server and logging
SERVER_NAME = "CoolColabMCP"
LOG_FILE_PREFIX = "cool-colab-mcp"
LOG_DIR_PREFIX = "cool-colab-mcp-logs-"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_FILE_TIMESTAMP = "%Y-%m-%d_%H-%M-%S"

# Doctor
DIST_NAME = "cool-colab-mcp"
MIN_PYTHON = (3, 13)

# Notebook tools exposed by the Colab frontend, proxied per session
ADD_CODE_CELL = "add_code_cell"
ADD_TEXT_CELL = "add_text_cell"
GET_CELLS = "get_cells"
RUN_CODE_CELL = "run_code_cell"
UPDATE_CELL = "update_cell"
DELETE_CELL = "delete_cell"
MOVE_CELL = "move_cell"

# Keys under which frontend results may carry a cell id
CELL_ID_KEYS = ("cellId", "cell_id", "id")
RESULT_KEY = "result"
