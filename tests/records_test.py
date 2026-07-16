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

import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from cool_colab_mcp import storage
from cool_colab_mcp.constants import (
    COLAB,
    DEFAULT_NOTEBOOK_ID,
    HOME_ENV,
    NOTEBOOK_DIRS_ENV,
    REGISTRY_STORE,
    STORAGE_SUFFIX,
)
from cool_colab_mcp.errors import ToolFailed
from cool_colab_mcp.registry.records import NotebookRecord, NotebookRegistry

DRIVE_URL = f"{COLAB}/drive/file-id-1"
OTHER_URL = f"{COLAB}/drive/file-id-2"


@pytest.fixture(autouse=True)
def home_override(tmp_path, monkeypatch):
    monkeypatch.setenv(HOME_ENV, str(tmp_path))
    return tmp_path


def record(notebook_id="training", **overrides) -> NotebookRecord:
    fields = {"notebook_id": notebook_id, "name": "Training", "url": DRIVE_URL}
    fields.update(overrides)
    return NotebookRecord(**fields)


class TestNotebookRecord:
    @pytest.mark.parametrize("bad_id", ["", DEFAULT_NOTEBOOK_ID])
    def test_empty_or_reserved_notebook_id_rejected(self, bad_id):
        with pytest.raises(ToolFailed) as failure:
            record(notebook_id=bad_id)
        assert failure.value.error.kind == "invalid_input"

    def test_url_validated_with_validate_notebook_url(self):
        with pytest.raises(ToolFailed) as failure:
            record(url="https://evil.com/drive/x")
        assert failure.value.error.kind == "invalid_input"

    def test_preferred_runtime_optional_and_stored(self):
        assert record().preferred_runtime is None
        assert record(preferred_runtime="gpu").preferred_runtime == "gpu"

    def test_exactly_one_remote_or_local_source_is_required(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv(NOTEBOOK_DIRS_ENV, str(tmp_path))
        path = tmp_path / "local.ipynb"
        path.write_text('{"cells":[],"metadata":{},"nbformat":4,"nbformat_minor":5}')
        with pytest.raises(ToolFailed) as missing:
            record(url=None)
        with pytest.raises(ToolFailed) as both:
            record(local_path=str(path))
        assert missing.value.error.kind == "invalid_input"
        assert both.value.error.kind == "invalid_input"

    def test_local_notebook_source_is_stored(self, tmp_path, monkeypatch):
        monkeypatch.setenv(NOTEBOOK_DIRS_ENV, str(tmp_path))
        path = tmp_path / "local.ipynb"
        path.write_text('{"cells":[],"metadata":{},"nbformat":4,"nbformat_minor":5}')
        local = record(url=None, local_path=str(path))
        assert local.local_path == str(path.resolve())


class TestNotebookRegistry:
    def test_corrupted_store_raises_structured_error(self, home_override):
        (home_override / f"{REGISTRY_STORE}{STORAGE_SUFFIX}").write_text("{not json")
        with pytest.raises(ToolFailed) as failure:
            NotebookRegistry().list()
        assert failure.value.error.kind == "protocol_error"

    def test_register_get_roundtrip(self):
        registry = NotebookRegistry()
        registry.register(record(preferred_runtime="gpu"))
        assert registry.get("training") == record(preferred_runtime="gpu")

    def test_list_all_records(self):
        registry = NotebookRegistry()
        registry.register(record("a"))
        registry.register(record("b", url=OTHER_URL))
        assert {r.notebook_id for r in registry.list()} == {"a", "b"}

    def test_concurrent_registrations_do_not_overwrite_records(self, monkeypatch):
        original_load = storage.load

        def slow_load(name):
            data = original_load(name)
            time.sleep(0.05)
            return data

        monkeypatch.setattr(storage, "load", slow_load)
        registry = NotebookRegistry()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(registry.register, [record("a"), record("b", url=OTHER_URL)]))

        assert {item.notebook_id for item in registry.list()} == {"a", "b"}

    def test_reregister_same_id_updates(self):
        registry = NotebookRegistry()
        registry.register(record())
        registry.register(record(name="Renamed", url=OTHER_URL))
        updated = registry.get("training")
        assert (updated.name, updated.url) == ("Renamed", OTHER_URL)
        assert len(registry.list()) == 1

    def test_remove(self):
        registry = NotebookRegistry()
        registry.register(record())
        registry.remove("training")
        assert registry.list() == []

    def test_concurrent_removals_do_not_restore_records(self, monkeypatch):
        registry = NotebookRegistry()
        registry.register(record("a"))
        registry.register(record("b", url=OTHER_URL))
        original_load = storage.load

        def slow_load(name):
            data = original_load(name)
            time.sleep(0.05)
            return data

        monkeypatch.setattr(storage, "load", slow_load)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(registry.remove, ["a", "b"]))

        assert registry.list() == []

    def test_get_unknown_raises_structured_error(self):
        with pytest.raises(ToolFailed) as failure:
            NotebookRegistry().get("missing")
        assert failure.value.error.kind == "unknown_notebook"
        assert failure.value.error.details == {"notebook_id": "missing"}

    def test_remove_unknown_raises_structured_error(self):
        with pytest.raises(ToolFailed) as failure:
            NotebookRegistry().remove("missing")
        assert failure.value.error.kind == "unknown_notebook"

    def test_persists_across_reinstantiation(self):
        NotebookRegistry().register(record(preferred_runtime="gpu"))
        # a fresh instance (as after a server restart) sees the same records
        assert NotebookRegistry().get("training") == record(preferred_runtime="gpu")

    def test_local_record_remains_removable_after_file_disappears(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv(NOTEBOOK_DIRS_ENV, str(tmp_path))
        path = tmp_path / "local.ipynb"
        path.write_text('{"cells":[],"metadata":{},"nbformat":4,"nbformat_minor":5}')
        registry = NotebookRegistry()
        registry.register(record(url=None, local_path=str(path)))
        path.unlink()
        assert registry.list()[0].local_path == str(path)
        registry.remove("training")
        assert registry.list() == []
