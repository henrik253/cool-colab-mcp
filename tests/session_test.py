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

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest
from conftest import fake_raw_result, mock_proxy_client

from cool_colab_mcp.constants import COLAB, NOTEBOOK_URL_ENV, SCRATCH_PATH
from cool_colab_mcp.errors import ToolFailed
from cool_colab_mcp.sessions import session

DRIVE_URL = f"{COLAB}/drive/file-id-1"
GITHUB_URL = f"{COLAB}/github/user/repo/blob/main/nb.ipynb"


def make_session(proxy=None) -> session.NotebookSession:
    """A NotebookSession wired to mocks at the WebSocket/proxy boundary."""
    nb_session = session.NotebookSession("nb-1")
    nb_session.proxy_client = proxy
    return nb_session


class TestValidateNotebookUrl:
    @pytest.mark.parametrize("url", [DRIVE_URL, GITHUB_URL])
    def test_accepted_forms(self, url):
        assert session.validate_notebook_url(url) == url

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.com/drive/file-id-1",
            "http://colab.research.google.com/drive/file-id-1",
            f"{COLAB}/notebooks/empty.ipynb",
            "not a url",
        ],
    )
    def test_rejected_forms(self, url):
        with pytest.raises(ToolFailed) as exc_info:
            session.validate_notebook_url(url)
        assert exc_info.value.error.kind == "invalid_input"
        assert exc_info.value.error.details == {"notebook_url": url}


class TestResolveNotebookUrl:
    def test_explicit_url_wins_and_becomes_active(self, monkeypatch):
        monkeypatch.setenv(NOTEBOOK_URL_ENV, f"{COLAB}/drive/env-pin")
        nb_session = make_session()
        assert nb_session.resolve_notebook_url(DRIVE_URL) == DRIVE_URL
        assert nb_session.active_notebook_url == DRIVE_URL

    def test_explicit_url_replaces_previous_active(self):
        nb_session = make_session()
        nb_session.resolve_notebook_url(DRIVE_URL)
        nb_session.cell_outputs["shared-id"] = [{"output_type": "stream"}]
        assert nb_session.resolve_notebook_url(GITHUB_URL) == GITHUB_URL
        assert nb_session.active_notebook_url == GITHUB_URL
        assert nb_session.cell_outputs == {}

    def test_reconnect_same_url_keeps_cached_outputs(self):
        nb_session = make_session()
        nb_session.resolve_notebook_url(DRIVE_URL)
        nb_session.cell_outputs["cell"] = []
        nb_session.resolve_notebook_url(DRIVE_URL)
        assert nb_session.cell_outputs == {"cell": []}

    def test_fallback_to_explicit_url_clears_cached_outputs(self, monkeypatch):
        monkeypatch.setenv(NOTEBOOK_URL_ENV, f"{COLAB}/drive/env-pin")
        nb_session = make_session()
        nb_session.resolve_notebook_url(None)
        nb_session.cell_outputs["shared-id"] = []
        nb_session.resolve_notebook_url(DRIVE_URL)
        assert nb_session.cell_outputs == {}

    def test_active_notebook_reused_without_parameter(self):
        nb_session = make_session()
        nb_session.resolve_notebook_url(DRIVE_URL)
        assert nb_session.resolve_notebook_url(None) == DRIVE_URL

    def test_env_pin_fallback(self, monkeypatch):
        monkeypatch.setenv(NOTEBOOK_URL_ENV, f"{COLAB}/drive/env-pin")
        assert make_session().resolve_notebook_url(None) == f"{COLAB}/drive/env-pin"

    def test_scratch_fallback(self, monkeypatch):
        monkeypatch.delenv(NOTEBOOK_URL_ENV, raising=False)
        assert make_session().resolve_notebook_url(None) == f"{COLAB}{SCRATCH_PATH}"

    def test_invalid_url_rejected_and_active_unchanged(self):
        nb_session = make_session()
        with pytest.raises(ToolFailed):
            nb_session.resolve_notebook_url("https://evil.com/drive/x")
        assert nb_session.active_notebook_url is None


class TestNotebookSessionCallTool:
    @pytest.mark.asyncio
    async def test_disconnected_raises_structured_error(self):
        nb_session = make_session()
        with pytest.raises(ToolFailed) as exc_info:
            await nb_session.call_tool("get_cells", {})
        assert exc_info.value.error.kind == "not_connected"
        assert exc_info.value.error.details == {"notebook_id": "nb-1"}

    @pytest.mark.asyncio
    async def test_forwards_and_strips_none_args(self):
        proxy = mock_proxy_client([fake_raw_result({"ok": True})])
        nb_session = make_session(proxy)

        result = await nb_session.call_tool(
            "add_code_cell", {"code": "1+1", "cellIndex": None}
        )

        proxy.call_tool.assert_awaited_once_with("add_code_cell", {"code": "1+1"})
        assert result.structured_content == {"ok": True}

    @pytest.mark.asyncio
    async def test_mid_call_drop_raises_structured_not_connected(self):
        proxy = mock_proxy_client()
        nb_session = make_session(proxy)

        async def drop(*args, **kwargs):
            proxy.is_connected.return_value = False  # the WebSocket just died
            raise ConnectionError("stream ends after 0 bytes")

        proxy.call_tool = AsyncMock(side_effect=drop)

        with pytest.raises(ToolFailed) as exc_info:
            await nb_session.call_tool("get_cells", {})
        assert exc_info.value.error.kind == "not_connected"
        assert exc_info.value.error.details == {"notebook_id": "nb-1"}
        assert isinstance(exc_info.value.__cause__, ConnectionError)

    @pytest.mark.asyncio
    async def test_error_while_still_connected_propagates(self):
        proxy = mock_proxy_client([RuntimeError("boom")])
        with pytest.raises(RuntimeError, match="boom"):
            await make_session(proxy).call_tool("get_cells", {})

    @pytest.mark.asyncio
    async def test_mid_call_drop_during_run_code(self):
        proxy = mock_proxy_client()
        nb_session = make_session(proxy)

        async def drop(*args, **kwargs):
            proxy.is_connected.return_value = False
            raise ConnectionError("Colab Frontend disconnected")

        proxy.call_tool = AsyncMock(side_effect=drop)

        with pytest.raises(ToolFailed) as exc_info:
            await nb_session.run_code("1+1")
        assert exc_info.value.error.kind == "not_connected"

    @pytest.mark.asyncio
    async def test_serializes_via_session_lock(self):
        proxy = mock_proxy_client()
        nb_session = make_session(proxy)

        await nb_session.lock.acquire()
        task = asyncio.create_task(nb_session.call_tool("get_cells", {}))
        await asyncio.sleep(0.01)
        assert not task.done()
        nb_session.lock.release()
        await task

        proxy.call_tool.assert_awaited_once()


class TestRunCode:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        proxy = mock_proxy_client(
            [
                fake_raw_result({"newCellId": "c-1"}),
                fake_raw_result({"output": "42", "outputs": []}),
            ]
        )
        nb_session = make_session(proxy)

        result = await nb_session.run_code("6*7")

        assert result == {"output": "42", "outputs": []}
        assert nb_session.cell_outputs == {"c-1": []}
        assert proxy.call_tool.await_args_list[0].args == (
            "add_code_cell",
            {"code": "6*7", "cellIndex": 0, "language": "python"},
        )
        assert proxy.call_tool.await_args_list[1].args == (
            "run_code_cell",
            {"cellId": "c-1"},
        )

    @pytest.mark.asyncio
    async def test_public_run_code_cell_caches_outputs_for_persistence(self):
        outputs = [{"output_type": "stream", "name": "stdout", "text": ["saved\n"]}]
        session = make_session(
            mock_proxy_client([fake_raw_result({"outputs": outputs})])
        )
        await session.call_tool("run_code_cell", {"cellId": "live-cell"})
        assert session.cell_outputs == {"live-cell": outputs}

    def test_cached_code_outputs_never_merge_into_markdown(self):
        session = make_session()
        session.cell_outputs["shared-id"] = []
        cells = [{"cellId": "shared-id", "type": "text", "content": "# Notes"}]
        assert session.merge_cached_outputs(cells) == cells

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "add_result",
        [
            fake_raw_result({"newCellId": "c-1"}),
            fake_raw_result(None, text='{"newCellId": "c-1"}'),
        ],
    )
    async def test_verified_cell_id_parsed_from_structured_or_text(self, add_result):
        proxy = mock_proxy_client([add_result, fake_raw_result({"output": "ok"})])

        await make_session(proxy).run_code("pass")

        assert proxy.call_tool.await_args_list[1].args[1] == {"cellId": "c-1"}

    @pytest.mark.asyncio
    async def test_unstructured_run_result_returned_as_text(self):
        proxy = mock_proxy_client(
            [fake_raw_result({"newCellId": "c-1"}), fake_raw_result(None, text="done")]
        )
        assert await make_session(proxy).run_code("pass") == {"text": "done"}

    @pytest.mark.asyncio
    async def test_missing_cell_id_fails(self):
        proxy = mock_proxy_client([fake_raw_result(None, text="no id here")])
        with pytest.raises(ToolFailed, match="no cell id") as exc_info:
            await make_session(proxy).run_code("pass")
        assert exc_info.value.error.kind == "protocol_error"

    @pytest.mark.asyncio
    async def test_proxy_failure_propagates(self):
        proxy = mock_proxy_client(
            [fake_raw_result({"newCellId": "c-1"}), ValueError("boom")]
        )
        with pytest.raises(ValueError, match="boom"):
            await make_session(proxy).run_code("pass")

    @pytest.mark.asyncio
    async def test_disconnected_raises_structured_error(self):
        with pytest.raises(ToolFailed) as exc_info:
            await make_session().run_code("pass")
        assert exc_info.value.error.kind == "not_connected"


class TestNotebookSessionLifecycle:
    @pytest.mark.asyncio
    @patch("cool_colab_mcp.sessions.session.ColabProxyClient")
    @patch("cool_colab_mcp.sessions.session.ColabWebSocketServer")
    async def test_start_owns_wss_and_proxy_client(self, mock_wss_cls, mock_proxy_cls):
        mock_wss_cls.return_value.__aenter__ = AsyncMock()
        mock_proxy_cls.return_value.__aenter__ = AsyncMock()
        nb_session = session.NotebookSession("nb-1")

        await nb_session.start()

        mock_wss_cls.assert_called_once()
        mock_proxy_cls.assert_called_once_with(nb_session.wss)
        await nb_session.aclose()

    def test_token_and_port_delegate_to_wss(self, mock_wss):
        nb_session = make_session()
        nb_session.wss = mock_wss
        assert nb_session.token == "test-token"
        assert nb_session.port == 1234

    @pytest.mark.asyncio
    async def test_await_connection_without_start_is_false(self):
        assert await make_session().await_connection(0.01) is False


class TestColabProxyClient:
    def test_is_connected(self, mock_wss):
        client = session.ColabProxyClient(mock_wss)
        assert client.is_connected() is False
        mock_wss.connection_live.set()
        assert client.is_connected() is False
        client.proxy_mcp_client = Mock()
        assert client.is_connected() is True

    @pytest.mark.asyncio
    async def test_await_connection_success(self, mock_wss):
        client = session.ColabProxyClient(mock_wss)
        client._start_task = asyncio.create_task(asyncio.sleep(0))
        client.proxy_mcp_client = Mock()
        mock_wss.connection_live.set()

        assert await client.await_connection(0.5) is True

    @pytest.mark.asyncio
    async def test_await_connection_timeout_keeps_start_task_alive(self, mock_wss):
        client = session.ColabProxyClient(mock_wss)
        client._start_task = asyncio.create_task(asyncio.sleep(10))

        assert await client.await_connection(0.05) is False
        assert not client._start_task.cancelled()

        client._start_task.cancel()

    @pytest.mark.asyncio
    async def test_await_connection_before_start_is_false(self, mock_wss):
        assert await session.ColabProxyClient(mock_wss).await_connection(0.05) is False

    @pytest.mark.asyncio
    @patch("cool_colab_mcp.sessions.session.Client")
    @patch(
        "cool_colab_mcp.sessions.session.ColabTransport", spec=session.ColabTransport
    )
    async def test_start_proxy_client(
        self, mock_colab_transport, mock_client, mock_wss
    ):
        mock_client.return_value.__aenter__ = AsyncMock()
        client = session.ColabProxyClient(mock_wss)
        mock_wss.connection_live.set()
        async with client:
            await client._start_task

        mock_colab_transport.assert_called_once_with(mock_wss)
        mock_client.assert_called_with(mock_colab_transport.return_value)

    @pytest.mark.asyncio
    async def test_call_tool_forwards_to_mcp_client(self, mock_wss):
        client = session.ColabProxyClient(mock_wss)
        client.proxy_mcp_client = Mock()
        client.proxy_mcp_client.call_tool = AsyncMock(return_value="raw")

        assert await client.call_tool("get_cells", {"a": 1}) == "raw"
        client.proxy_mcp_client.call_tool.assert_awaited_once_with(
            "get_cells", {"a": 1}
        )

    @pytest.mark.asyncio
    async def test_aexit_cancels_pending_start(self, mock_wss):
        client = session.ColabProxyClient(mock_wss)
        async with client:
            assert client._start_task is not None
        assert client._start_task.cancelled()


class TestColabTransport:
    @pytest.mark.asyncio
    @patch("cool_colab_mcp.sessions.session.ClientSession")
    async def test_connect_session(self, mock_client_session, mock_wss):
        transport = session.ColabTransport(mock_wss)
        mock_client_session.return_value.__aenter__ = AsyncMock()
        async with transport.connect_session(foo="bar") as client_session:
            assert (
                client_session
                == mock_client_session.return_value.__aenter__.return_value
            )

        mock_client_session.assert_called_once_with(
            mock_wss.read_stream, mock_wss.write_stream, foo="bar"
        )
