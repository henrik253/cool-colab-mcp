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

import logging
import re
import webbrowser
from unittest.mock import Mock

import pytest
from fastmcp import Client

from cool_colab_mcp import logging_setup, parse_args, process_registry, server
from cool_colab_mcp.constants import NOTEBOOK_URL_ENV
from cool_colab_mcp.logging_setup import init_logging
from cool_colab_mcp.server import build_server
from cool_colab_mcp.sessions import manager as manager_module
from cool_colab_mcp.sessions import session as session_module
from cool_colab_mcp.sessions import websocket_server as wss_module
from cool_colab_mcp.sessions.manager import SessionManager


@pytest.fixture(autouse=True)
def restore_root_logger():
    """Undo whatever init_logging did to the root logger."""
    root = logging.getLogger()
    handlers_before = root.handlers[:]
    level_before = root.level
    yield
    for handler in root.handlers[:]:
        if handler not in handlers_before:
            handler.close()
            root.removeHandler(handler)
    root.setLevel(level_before)


class TestInitLogging:
    def test_record_format_has_timestamp_level_name_message(self, tmp_path):
        log_file = init_logging(str(tmp_path))
        logging.getLogger("cool_colab_mcp.sessions.session").info("hello notebook")
        assert re.search(
            r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} "
            r"INFO cool_colab_mcp\.sessions\.session: hello notebook$",
            log_file.read_text(),
            re.MULTILINE,
        )

    def test_logs_its_own_destination(self, tmp_path):
        log_file = init_logging(str(tmp_path))
        assert str(log_file) in log_file.read_text()

    def test_default_level_is_info(self, tmp_path):
        log_file = init_logging(str(tmp_path))
        logging.getLogger("cool_colab_mcp.x").debug("invisible")
        assert logging.getLogger().level == logging.INFO
        assert "invisible" not in log_file.read_text()

    def test_verbose_enables_debug(self, tmp_path):
        log_file = init_logging(str(tmp_path), verbose=True)
        logging.getLogger("cool_colab_mcp.x").debug("now visible")
        assert logging.getLogger().level == logging.DEBUG
        assert "now visible" in log_file.read_text()

    def test_verbose_flag_parses_and_sets_debug(self, tmp_path):
        args = parse_args(["--verbose", "--log", str(tmp_path)])
        assert args.verbose
        init_logging(args.log, verbose=args.verbose)
        assert logging.getLogger().level == logging.DEBUG

    def test_missing_log_dir_raises(self, tmp_path):
        with pytest.raises(OSError):
            init_logging(str(tmp_path / "does-not-exist"))


class TestNamespacedLoggers:
    @pytest.mark.parametrize(
        "module",
        [logging_setup, server, manager_module, session_module, wss_module],
        ids=lambda module: module.__name__,
    )
    def test_module_logger_is_namespaced_after_its_module(self, module):
        assert module.logger.name == module.__name__
        assert module.logger.name.startswith("cool_colab_mcp.")

    @pytest.mark.asyncio
    async def test_registry_failure_uses_websocket_module_logger(
        self, monkeypatch, caplog
    ):
        def fail_to_register(*args, **kwargs):
            raise OSError("registry unavailable")

        monkeypatch.setattr(process_registry, "register", fail_to_register)
        caplog.set_level(logging.WARNING)

        async with wss_module.ColabWebSocketServer():
            pass

        record = next(
            record
            for record in caplog.records
            if "registry unavailable" in record.message
        )
        assert record.name == wss_module.__name__


class TestNoSecretsInLogs:
    @pytest.mark.asyncio
    async def test_session_token_never_logged_when_opening_connection(
        self, tmp_path, monkeypatch, caplog
    ):
        monkeypatch.setattr(webbrowser, "open_new", Mock())
        monkeypatch.setattr("cool_colab_mcp.server.UI_CONNECTION_TIMEOUT", 0.05)
        monkeypatch.delenv(NOTEBOOK_URL_ENV, raising=False)
        caplog.set_level(logging.DEBUG)
        log_file = init_logging(str(tmp_path), verbose=True)

        manager = SessionManager()
        try:
            async with Client(build_server(manager)) as client:
                await client.call_tool("open_colab_browser_connection", {})
            token = manager.get().token
        finally:
            await manager.aclose()

        assert token  # sanity: a real token was minted
        assert caplog.text  # sanity: something was logged
        assert token not in caplog.text
        assert token not in log_file.read_text()
