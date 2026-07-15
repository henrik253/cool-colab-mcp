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

"""Atomic JSON store for persistent local state (registry, snapshots, and auth build on it)."""

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from filelock import FileLock

from cool_colab_mcp.constants import (
    DEFAULT_HOME_DIR,
    HOME_ENV,
    STORAGE_LOCK_SUFFIX,
    STORAGE_SUFFIX,
)


def base_dir() -> Path:
    """The local state directory: $COOL_COLAB_MCP_HOME or ~/.cool-colab-mcp."""
    home = os.environ.get(HOME_ENV)
    return Path(home) if home else Path(DEFAULT_HOME_DIR).expanduser()


def _path(name: str) -> Path:
    return base_dir() / f"{name}{STORAGE_SUFFIX}"


def lock(name: str) -> FileLock:
    """Inter-process lock for an atomic read-modify-write store transaction."""
    return FileLock(base_dir() / f"{name}{STORAGE_LOCK_SUFFIX}")


def load(name: str) -> dict[str, Any]:
    """Read the named store; an absent store is an empty dict."""
    path = _path(name)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save(name: str, data: dict[str, Any]) -> None:
    """Write the named store atomically (temp file in the same directory + os.replace)."""
    path = _path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{name}-")
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(data, file, indent=2)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
