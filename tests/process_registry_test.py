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

import os
import signal
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from cool_colab_mcp import process_registry, storage
from cool_colab_mcp.constants import PROCESS_REGISTRY_STORE

DEAD_PID = 4_000_001
FOREIGN_PID = 4_000_002


@pytest.fixture
def fake_liveness(monkeypatch):
    """Only the current process and FOREIGN_PID count as alive."""
    alive = {os.getpid(), FOREIGN_PID}
    monkeypatch.setattr(process_registry, "is_alive", lambda pid: pid in alive)
    return alive


def seed(pid: int, port: int) -> None:
    entry = process_registry.ServerEntry(
        pid=pid, port=port, host="localhost", started_at=time.time()
    )
    data = storage.load(PROCESS_REGISTRY_STORE)
    data[f"{pid}:{port}"] = entry.model_dump()
    storage.save(PROCESS_REGISTRY_STORE, data)


class TestRegister:
    def test_records_current_process(self):
        before = time.time()
        entry = process_registry.register(port=4242, host="localhost")

        assert entry.pid == os.getpid()
        assert entry.port == 4242
        assert entry.host == "localhost"
        assert before <= entry.started_at <= time.time()
        assert process_registry.list_running() == [entry]

    def test_prunes_dead_entries_on_the_way(self, fake_liveness):
        seed(DEAD_PID, 1111)
        process_registry.register(port=4242, host="localhost")
        pids = {e.pid for e in process_registry.list_running()}
        assert pids == {os.getpid()}
        assert DEAD_PID not in {
            e["pid"] for e in storage.load(PROCESS_REGISTRY_STORE).values()
        }

    def test_one_entry_per_port_of_the_same_process(self):
        process_registry.register(port=4242, host="localhost")
        process_registry.register(port=4343, host="localhost")
        assert {e.port for e in process_registry.list_running()} == {4242, 4343}

    def test_concurrent_registrations_do_not_overwrite_each_other(self, monkeypatch):
        original_load = storage.load

        def slow_load(name):
            data = original_load(name)
            time.sleep(0.05)
            return data

        monkeypatch.setattr(storage, "load", slow_load)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(
                pool.map(
                    lambda port: process_registry.register(port, "localhost"),
                    [4242, 4343],
                )
            )

        assert {entry.port for entry in process_registry.list_running()} == {4242, 4343}


class TestUnregister:
    def test_removes_only_the_named_port(self):
        process_registry.register(port=4242, host="localhost")
        process_registry.register(port=4343, host="localhost")

        process_registry.unregister(4242)

        assert {e.port for e in process_registry.list_running()} == {4343}

    def test_unknown_port_is_a_no_op(self):
        process_registry.register(port=4242, host="localhost")
        process_registry.unregister(9999)
        assert {e.port for e in process_registry.list_running()} == {4242}

    def test_concurrent_unregistrations_do_not_restore_entries(self, monkeypatch):
        process_registry.register(port=4242, host="localhost")
        process_registry.register(port=4343, host="localhost")
        original_load = storage.load

        def slow_load(name):
            data = original_load(name)
            time.sleep(0.05)
            return data

        monkeypatch.setattr(storage, "load", slow_load)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(process_registry.unregister, [4242, 4343]))

        assert process_registry.list_running() == []


class TestPruneDead:
    def test_removes_dead_keeps_alive(self, fake_liveness):
        seed(DEAD_PID, 1111)
        seed(FOREIGN_PID, 2222)

        assert process_registry.prune_dead() == 1

        remaining = storage.load(PROCESS_REGISTRY_STORE)
        assert set(remaining) == {f"{FOREIGN_PID}:2222"}

    def test_nothing_to_prune(self, fake_liveness):
        seed(FOREIGN_PID, 2222)
        assert process_registry.prune_dead() == 0


class TestListRunning:
    def test_filters_dead_pids(self, fake_liveness):
        seed(DEAD_PID, 1111)
        seed(FOREIGN_PID, 2222)
        assert [e.pid for e in process_registry.list_running()] == [FOREIGN_PID]

    def test_empty_registry(self):
        assert process_registry.list_running() == []


class TestKillStale:
    def test_kills_foreign_and_drops_dead_but_never_self(
        self, fake_liveness, monkeypatch
    ):
        killed: list[int] = []
        monkeypatch.setattr(
            process_registry, "_terminate", lambda pid: killed.append(pid) or True
        )
        seed(DEAD_PID, 1111)
        seed(FOREIGN_PID, 2222)
        seed(os.getpid(), 3333)

        removed = process_registry.kill_stale()

        assert killed == [FOREIGN_PID]
        assert {e.pid for e in removed} == {DEAD_PID, FOREIGN_PID}
        assert {e.pid for e in process_registry.list_running()} == {os.getpid()}

    def test_unkillable_entry_is_kept(self, fake_liveness, monkeypatch):
        monkeypatch.setattr(process_registry, "_terminate", lambda pid: False)
        seed(FOREIGN_PID, 2222)

        assert process_registry.kill_stale() == []
        assert [e.pid for e in process_registry.list_running()] == [FOREIGN_PID]


class TestCorruptRegistry:
    def test_invalid_json_is_ignored(self):
        storage.save("placeholder", {})  # ensure the base dir exists
        path = storage.base_dir() / f"{PROCESS_REGISTRY_STORE}.json"
        path.write_text("not json at all")

        assert process_registry.list_running() == []

    def test_wrong_shape_is_ignored(self):
        storage.save(PROCESS_REGISTRY_STORE, {"weird": {"nope": True}})
        assert process_registry.list_running() == []


class TestTerminate:
    @pytest.fixture(autouse=True)
    def fast_grace(self, monkeypatch):
        monkeypatch.setattr(process_registry, "KILL_GRACE_TIMEOUT", 0.05)
        monkeypatch.setattr(process_registry, "KILL_POLL_INTERVAL", 0.01)

    def test_sigterm_suffices(self, monkeypatch):
        state = {"alive": True}
        monkeypatch.setattr(process_registry, "is_alive", lambda pid: state["alive"])
        monkeypatch.setattr("os.kill", lambda pid, sig: state.update(alive=False))
        assert process_registry._terminate(FOREIGN_PID) is True

    def test_escalates_to_sigkill(self, monkeypatch):
        signals: list[int] = []
        state = {"alive": True}

        def kill(pid, sig):
            signals.append(sig)
            if sig == signal.SIGKILL:
                state["alive"] = False

        monkeypatch.setattr(process_registry, "is_alive", lambda pid: state["alive"])
        monkeypatch.setattr("os.kill", kill)

        assert process_registry._terminate(FOREIGN_PID) is True
        assert signals == [signal.SIGTERM, signal.SIGKILL]

    def test_gives_up_on_immortal_process(self, monkeypatch):
        monkeypatch.setattr(process_registry, "is_alive", lambda pid: True)
        monkeypatch.setattr("os.kill", lambda pid, sig: None)
        assert process_registry._terminate(FOREIGN_PID) is False
