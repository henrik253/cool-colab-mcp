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

# Timeouts
UI_CONNECTION_TIMEOUT = 60.0  # secs

# Sessions
DEFAULT_NOTEBOOK_ID = "default"

# Environment variables
NOTEBOOK_URL_ENV = "COLAB_MCP_NOTEBOOK_URL"  # legacy notebook pin (headless callers)
HOME_ENV = "COOL_COLAB_MCP_HOME"

# Persistent local storage
DEFAULT_HOME_DIR = "~/.cool-colab-mcp"
STORAGE_SUFFIX = ".json"

# Server and logging
SERVER_NAME = "CoolColabMCP"
LOGGER_NAME = "cool-colab-mcp"
LOG_FILE_PREFIX = "cool-colab-mcp"
LOG_DIR_PREFIX = "cool-colab-mcp-logs-"

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
