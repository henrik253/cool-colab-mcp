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

import importlib.metadata
import sys
from types import SimpleNamespace

import pytest

from cool_colab_mcp import doctor, main, parse_args, process_registry
from cool_colab_mcp.constants import HOME_ENV, NOTEBOOK_URL_ENV


@pytest.fixture
def healthy_env(tmp_path, monkeypatch):
    """A fully passing environment: writable storage and log dirs, no env pin."""
    monkeypatch.setenv(HOME_ENV, str(tmp_path / "home"))
    monkeypatch.delenv(NOTEBOOK_URL_ENV, raising=False)
    return str(tmp_path / "logs")


@pytest.fixture
def file_as_dir(tmp_path):
    """A path that cannot become a directory because a file already sits there."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    return str(blocker)


class TestChecks:
    def test_all_checks_pass_in_healthy_env(self, healthy_env):
        results = doctor.run_checks(healthy_env)
        assert results and all(result.ok for result in results)

    def test_python_version_too_old_fails(self, monkeypatch):
        monkeypatch.setattr(sys, "version_info", (3, 10, 0, "final", 0))
        name, ok, hint = doctor.check_python_version()
        assert not ok
        assert "3.10.0" in hint

    def test_package_metadata_missing_fails(self, monkeypatch):
        def missing(_name):
            raise importlib.metadata.PackageNotFoundError

        monkeypatch.setattr(doctor.importlib.metadata, "version", missing)
        name, ok, hint = doctor.check_package_version()
        assert not ok
        assert "uv sync" in hint

    def test_storage_dir_blocked_by_file_fails(self, monkeypatch, file_as_dir):
        monkeypatch.setenv(HOME_ENV, file_as_dir)
        name, ok, hint = doctor.check_storage_dir()
        assert not ok
        assert HOME_ENV in hint

    def test_log_dir_blocked_by_file_fails(self, file_as_dir):
        name, ok, hint = doctor.check_log_dir(file_as_dir)
        assert not ok
        assert "--log" in hint

    def test_port_bind_failure_fails(self, monkeypatch):
        def boom(*args, **kwargs):
            raise OSError("no sockets for you")

        monkeypatch.setattr(doctor.socket, "socket", boom)
        name, ok, hint = doctor.check_websocket_port()
        assert not ok
        assert "no sockets for you" in hint

    def test_env_pin_is_informational_either_way(self, monkeypatch):
        monkeypatch.setenv(NOTEBOOK_URL_ENV, "https://example.com/nb")
        assert doctor.check_notebook_env_pin().ok
        assert "set" in doctor.check_notebook_env_pin().hint

        monkeypatch.delenv(NOTEBOOK_URL_ENV)
        assert doctor.check_notebook_env_pin().ok
        assert "not set" in doctor.check_notebook_env_pin().hint

    def test_no_stale_servers_passes(self, monkeypatch):
        monkeypatch.setattr(process_registry, "list_running", lambda: [])
        assert doctor.check_stale_servers().ok

    def test_registered_servers_fail_with_cleanup_hint(self, monkeypatch):
        monkeypatch.setattr(
            process_registry,
            "list_running",
            lambda: [SimpleNamespace(pid=123, port=4567)],
        )
        result = doctor.check_stale_servers()
        assert not result.ok
        assert "--kill-stale" in result.hint

    def test_registry_read_failure_is_actionable(self, monkeypatch):
        def fail_to_read():
            raise OSError("permission denied")

        monkeypatch.setattr(process_registry, "list_running", fail_to_read)
        result = doctor.check_stale_servers()
        assert not result.ok
        assert HOME_ENV in result.hint


class TestMain:
    def test_exit_zero_and_pass_lines_when_healthy(self, healthy_env, capsys):
        assert doctor.main(healthy_env) == 0
        out = capsys.readouterr().out
        assert out.count("[PASS]") == len(doctor.run_checks(healthy_env))
        assert "[FAIL]" not in out

    def test_exit_one_and_fail_line_on_failure(self, healthy_env, file_as_dir, capsys):
        assert doctor.main(file_as_dir) == 1
        assert "[FAIL]" in capsys.readouterr().out

    def test_cli_doctor_subcommand_exits_with_check_status(
        self, healthy_env, monkeypatch, capsys
    ):
        monkeypatch.setattr(
            sys, "argv", ["cool-colab-mcp", "--log", healthy_env, "doctor"]
        )
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 0
        assert "[PASS]" in capsys.readouterr().out


class TestParseArgs:
    def test_doctor_subcommand_parsed(self):
        assert parse_args(["doctor"]).command == "doctor"

    def test_default_is_serve(self):
        assert parse_args([]).command is None
