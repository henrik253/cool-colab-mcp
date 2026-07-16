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
UPLOAD_DIRS_ENV = "COOL_COLAB_MCP_UPLOAD_DIRS"
NOTEBOOK_DIRS_ENV = "COOL_COLAB_MCP_NOTEBOOK_DIRS"

# Direct runtime file transfer
RUNTIME_ROOT = "/content"
UPLOAD_CHUNK_SIZE = 256 * 1024

# Persistent local storage
DEFAULT_HOME_DIR = "~/.cool-colab-mcp"
STORAGE_SUFFIX = ".json"
STORAGE_LOCK_SUFFIX = ".lock"
PROCESS_REGISTRY_STORE = "servers"  # storage.py store of running WebSocket servers
REGISTRY_STORE = "registry"  # storage.py store holding the notebook registry
SNAPSHOT_DIR_NAME = "snapshots"
SNAPSHOT_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S%fZ"
NOTEBOOK_SUFFIX = ".ipynb"
IPYNB_FORMAT = 4
IPYNB_MINOR_FORMAT = 5

# Authentication (plan.md §3). Scopes and the fixed OAuth callback port are taken
# from the reference fork SebastianGilPinzon/colab-mcp (Apache 2.0), src/colab_mcp/auth.py;
# the fixed port 8085 is its fix for the OAuth redirect-URI mismatch on ephemeral ports.
OAUTH_SCOPES = (
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/colaboratory",
    "openid",
)
OAUTH_LOCAL_SERVER_PORT = 8085
KEYRING_SERVICE = "cool-colab-mcp"
KEYRING_TOKEN_ACCOUNT = "google-oauth-token"

# Persistent browser profile directory under the base dir (storage.base_dir()).
# Phase 1 groundwork only; Chromium profile management lands in Phase 2 (plan.md §10).
BROWSER_PROFILE_DIR_NAME = "browser-profile"

# Colab runtime API (ported from SebastianGilPinzon/colab-mcp, Apache 2.0).
COLAB_RUNTIME_API = COLAB
COLAB_AUTH_USER_PARAM = "authuser"
COLAB_AUTH_USER = "0"
RUNTIME_ASSIGN_PATH = "/tun/m/assign"
RUNTIME_ASSIGNMENTS_PATH = "/tun/m/assignments"
RUNTIME_UNASSIGN_PATH_PREFIX = "/tun/m/unassign/"
COLAB_CLIENT_AGENT = "python-colab-client"
XSSI_PREFIX = ")]}'\n"
RUNTIME_PROFILES = {
    "prototype-cpu": "NONE",
    "debug-gpu": "T4",
    "training-gpu": "L4",
}
RUNTIME_ACCELERATORS = ("NONE", "T4", "L4", "A100", "V2-8", "V5E-1", "V6E-1")
RUNTIME_DENIAL_OUTCOMES = (
    "DENYLISTED",
    "QUOTA_DENIED_REQUESTED_VARIANTS",
    "QUOTA_EXCEEDED_USAGE_TIME",
)
RUNTIME_STATUS_CODE = """import json, platform
try:
 import torch
 gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
except Exception:
 gpu = None
print(json.dumps({'connected': True, 'accelerator': gpu or 'CPU', 'python': platform.python_version()}))"""
RUNTIME_MANIFEST_CODE = """import json, pathlib, subprocess, sys
p = pathlib.Path('/content/cool-colab-runtime-manifest.json')
p.write_text(json.dumps({'python': sys.version, 'packages': subprocess.check_output([sys.executable, '-m', 'pip', 'freeze'], text=True).splitlines()}))
print(str(p))"""

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
DEFAULT_CODE_LANGUAGE = "python"
DEFAULT_CODE_CELL_INDEX = 0
DEFAULT_TEXT_CELL_INDEX = -1
ADD_CODE_CELL = "add_code_cell"
ADD_TEXT_CELL = "add_text_cell"
GET_CELLS = "get_cells"
RUN_CODE_CELL = "run_code_cell"
UPDATE_CELL = "update_cell"
DELETE_CELL = "delete_cell"
MOVE_CELL = "move_cell"

# Keys under which frontend results may carry a cell id
CELL_ID_KEYS = ("newCellId",)

# Managed browser (plan.md §10/§11)
BROWSER_PROFILE_DIR_NAME = "browser-profile"
# Chrome's Local Network Access permission. A public origin (Colab) reaching localhost
# needs this; the older Private Network Access response headers do NOT satisfy it.
LOCAL_NETWORK_PERMISSION = "local-network-access"
DIALOG_TIMEOUT_MS = 60_000
