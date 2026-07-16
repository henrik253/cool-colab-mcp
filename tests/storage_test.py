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

from pathlib import Path

import pytest

from cool_colab_mcp import storage
from cool_colab_mcp.constants import DEFAULT_HOME_DIR, HOME_ENV


@pytest.fixture(autouse=True)
def home_override(tmp_path, monkeypatch):
    monkeypatch.setenv(HOME_ENV, str(tmp_path))
    return tmp_path


def test_roundtrip():
    data = {"notebooks": [{"id": "nb-1"}], "count": 1}
    storage.save("registry", data)
    assert storage.load("registry") == data


def test_missing_store_loads_empty():
    assert storage.load("nothing-here") == {}


def test_save_creates_base_dir(home_override):
    storage.save("registry", {})
    assert (home_override / "registry.json").exists()


def test_home_env_override(home_override):
    assert storage.base_dir() == home_override


def test_default_base_dir_without_env(monkeypatch):
    monkeypatch.delenv(HOME_ENV)
    assert storage.base_dir() == Path(DEFAULT_HOME_DIR).expanduser()


def test_failed_save_leaves_no_partial_file(home_override):
    storage.save("registry", {"good": True})

    with pytest.raises(TypeError):
        storage.save("registry", {"bad": object()})  # not JSON-serializable

    assert storage.load("registry") == {"good": True}
    assert [p.name for p in home_override.iterdir()] == ["registry.json"]
