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

"""CLI entry point (`cool_colab_mcp/__init__.py`): registry flags and startup."""

import sys
import time
from unittest.mock import AsyncMock, Mock

import pytest

import cool_colab_mcp
from cool_colab_mcp import process_registry

FOREIGN_PID = 4_000_002


@pytest.fixture(autouse=True)
def no_real_server(monkeypatch):
    """main_async must never start a real MCP server in unit tests."""
    server = Mock()
    server.run_async = AsyncMock()
    build = Mock(return_value=server)
    monkeypatch.setattr(cool_colab_mcp, "build_server", build)
    return build


def run_cli(monkeypatch, *flags: str) -> None:
    monkeypatch.setattr(sys, "argv", ["cool-colab-mcp", *flags])
    import asyncio

    asyncio.run(cool_colab_mcp.main_async())


def seed_foreign_entry(monkeypatch) -> None:
    monkeypatch.setattr(process_registry, "is_alive", lambda pid: True)
    entry = process_registry.ServerEntry(
        pid=FOREIGN_PID, port=4242, host="localhost", started_at=time.time()
    )
    from cool_colab_mcp import storage
    from cool_colab_mcp.constants import PROCESS_REGISTRY_STORE

    storage.save(PROCESS_REGISTRY_STORE, {f"{FOREIGN_PID}:4242": entry.model_dump()})


class TestParseArgs:
    def test_flags_default_off(self):
        args = cool_colab_mcp.parse_args([])
        assert args.list_running is False
        assert args.kill_stale is False

    def test_flags_recognized(self):
        assert cool_colab_mcp.parse_args(["--list-running"]).list_running is True
        assert cool_colab_mcp.parse_args(["--kill-stale"]).kill_stale is True


class TestListRunning:
    def test_prints_entries_and_exits_before_serving(
        self, monkeypatch, capsys, no_real_server
    ):
        seed_foreign_entry(monkeypatch)

        run_cli(monkeypatch, "--list-running")

        out = capsys.readouterr().out
        assert f"pid={FOREIGN_PID}" in out
        assert "port=4242" in out
        no_real_server.assert_not_called()

    def test_empty_registry_prints_notice(self, monkeypatch, capsys, no_real_server):
        run_cli(monkeypatch, "--list-running")
        assert "No running" in capsys.readouterr().out
        no_real_server.assert_not_called()


class TestKillStale:
    def test_kills_and_reports_then_exits(self, monkeypatch, capsys, no_real_server):
        seed_foreign_entry(monkeypatch)
        killed: list[int] = []
        monkeypatch.setattr(
            process_registry, "_terminate", lambda pid: killed.append(pid) or True
        )

        run_cli(monkeypatch, "--kill-stale")

        assert killed == [FOREIGN_PID]
        assert f"removed pid={FOREIGN_PID} port=4242" in capsys.readouterr().out
        no_real_server.assert_not_called()

    def test_nothing_stale_prints_notice(self, monkeypatch, capsys, no_real_server):
        run_cli(monkeypatch, "--kill-stale")
        assert "No stale" in capsys.readouterr().out
        no_real_server.assert_not_called()


class TestNormalStartup:
    def test_prunes_dead_entries_then_serves(self, monkeypatch, no_real_server):
        pruned = Mock(return_value=0)
        monkeypatch.setattr(process_registry, "prune_dead", pruned)

        run_cli(monkeypatch)

        pruned.assert_called_once()
        no_real_server.assert_called_once()
        no_real_server.return_value.run_async.assert_awaited_once()
