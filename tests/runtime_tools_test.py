"""Tests for the static runtime-control tool surface."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from fastmcp import Client

from cool_colab_mcp.server import build_server
from cool_colab_mcp.errors import fail
from cool_colab_mcp.sessions.manager import SessionManager


@pytest_asyncio.fixture
async def manager():
    manager = SessionManager()
    yield manager
    await manager.aclose()


@pytest.fixture
def runtime_api(monkeypatch):
    api = Mock()
    api.list_assignments.return_value = [
        {"endpoint": "vm-1"},
        {"endpoint": "vm-2"},
    ]
    api.assign.return_value = {"accelerator": "T4", "outcome": "SUCCESS"}
    monkeypatch.setattr(
        "cool_colab_mcp.runtime.tools.ensure_credentials", lambda path: Mock()
    )
    monkeypatch.setattr("cool_colab_mcp.runtime.tools.RuntimeClient", lambda creds: api)
    return api


async def connected(manager):
    session = await manager.get_or_create("nb")
    session.run_code = AsyncMock(side_effect=[{"manifest": True}])
    return session


@pytest.mark.asyncio
async def test_status_without_session_returns_structured_error(manager):
    async with Client(build_server(manager)) as client:
        result = await client.call_tool(
            "get_runtime_status", {"notebook_id": "missing"}
        )
    assert result.structured_content["error"]["kind"] == "unknown_notebook"


@pytest.mark.asyncio
async def test_status_uses_shared_run_code(manager):
    session = await connected(manager)
    session.run_code.side_effect = [{"accelerator": "CPU"}]
    async with Client(build_server(manager)) as client:
        result = await client.call_tool("get_runtime_status", {"notebook_id": "nb"})
    assert result.structured_content["runtime"] == {"accelerator": "CPU"}
    session.run_code.assert_awaited_once()


@pytest.mark.asyncio
async def test_connect_runtime_verifies_hardware(manager):
    session = await connected(manager)
    session.run_code.side_effect = [{"accelerator": "T4"}]
    async with Client(build_server(manager)) as client:
        result = await client.call_tool("connect_runtime", {"notebook_id": "nb"})
    assert result.structured_content["runtime"] == {"accelerator": "T4"}


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["get_runtime_status", "connect_runtime"])
async def test_status_backend_failure_is_structured(manager, tool):
    session = await connected(manager)
    session.run_code.side_effect = fail("protocol_error", "frontend failed")
    async with Client(build_server(manager)) as client:
        result = await client.call_tool(tool, {"notebook_id": "nb"})
    assert result.structured_content["error"]["kind"] == "protocol_error"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,args",
    [
        ("get_runtime_status", {}),
        ("connect_runtime", {}),
        ("disconnect_runtime", {}),
        ("stop_runtime", {"preservation_confirmed": True}),
        (
            "restart_runtime",
            {"preservation_confirmed": True, "assignment_endpoint": "vm-1"},
        ),
        (
            "request_runtime_profile",
            {
                "profile": "debug-gpu",
                "preservation_confirmed": True,
                "assignment_endpoint": "vm-1",
            },
        ),
    ],
)
async def test_every_runtime_tool_rejects_bad_notebook(
    manager, runtime_api, tool, args
):
    async with Client(build_server(manager, Path("oauth.json"))) as client:
        result = await client.call_tool(tool, {**args, "notebook_id": "missing"})
    assert result.structured_content["error"]["kind"] == "unknown_notebook"


@pytest.mark.asyncio
async def test_profile_preserves_then_switches(manager, runtime_api):
    session = await connected(manager)
    async with Client(build_server(manager, Path("oauth.json"))) as client:
        result = await client.call_tool(
            "request_runtime_profile",
            {
                "profile": "debug-gpu",
                "notebook_id": "nb",
                "preservation_confirmed": True,
                "assignment_endpoint": "vm-1",
            },
        )
    assert result.structured_content["requested_accelerator"] == "T4"
    assert (
        result.structured_content["preservation"][
            "external_preservation_confirmed_by_caller"
        ]
        is True
    )
    assert session.run_code.await_count == 1
    runtime_api.unassign.assert_called_once_with("vm-1")
    runtime_api.assign.assert_called_once_with("T4")


@pytest.mark.asyncio
async def test_profile_sequence_is_manifest_release_assign(manager, runtime_api):
    events = []
    session = await connected(manager)
    session.run_code.side_effect = lambda code: events.append("manifest") or {}
    runtime_api.list_assignments.side_effect = lambda: events.append("list") or [
        {"endpoint": "vm-1"},
        {"endpoint": "vm-2"},
    ]
    runtime_api.unassign.side_effect = lambda endpoint: events.append(
        f"release:{endpoint}"
    )
    runtime_api.assign.side_effect = lambda accelerator: events.append(
        f"assign:{accelerator}"
    ) or {"outcome": "SUCCESS"}
    async with Client(build_server(manager, Path("oauth.json"))) as client:
        await client.call_tool(
            "request_runtime_profile",
            {
                "profile": "debug-gpu",
                "notebook_id": "nb",
                "preservation_confirmed": True,
                "assignment_endpoint": "vm-2",
            },
        )
    assert events == ["manifest", "list", "release:vm-2", "assign:T4"]


@pytest.mark.asyncio
async def test_unknown_profile_is_invalid_input(manager):
    async with Client(build_server(manager)) as client:
        result = await client.call_tool("request_runtime_profile", {"profile": "magic"})
    assert result.structured_content["error"]["kind"] == "invalid_input"


@pytest.mark.asyncio
async def test_switch_without_oauth_is_actionable(manager):
    await connected(manager)
    async with Client(build_server(manager)) as client:
        result = await client.call_tool(
            "request_runtime_profile", {"profile": "debug-gpu", "notebook_id": "nb"}
        )
    assert result.structured_content["error"]["kind"] == "user_action_required"


@pytest.mark.asyncio
async def test_switch_requires_preservation_confirmation(manager, runtime_api):
    session = await connected(manager)
    async with Client(build_server(manager, Path("oauth.json"))) as client:
        result = await client.call_tool(
            "request_runtime_profile", {"profile": "debug-gpu", "notebook_id": "nb"}
        )
    assert result.structured_content["error"]["kind"] == "user_action_required"
    session.run_code.assert_not_awaited()
    runtime_api.assign.assert_not_called()


@pytest.mark.asyncio
async def test_stop_without_mapping_releases_nothing(manager, runtime_api):
    await connected(manager)
    async with Client(build_server(manager, Path("oauth.json"))) as client:
        result = await client.call_tool(
            "stop_runtime",
            {"notebook_id": "nb", "preservation_confirmed": True},
        )
    assert result.structured_content["error"]["kind"] == "user_action_required"
    assert result.structured_content["error"]["details"]["assignment_endpoints"] == [
        "vm-1",
        "vm-2",
    ]
    runtime_api.unassign.assert_not_called()


@pytest.mark.asyncio
async def test_stop_releases_only_selected_assignment(manager, runtime_api):
    await connected(manager)
    async with Client(build_server(manager, Path("oauth.json"))) as client:
        result = await client.call_tool(
            "stop_runtime",
            {
                "notebook_id": "nb",
                "preservation_confirmed": True,
                "assignment_endpoint": "vm-2",
            },
        )
    assert result.structured_content["released"] == 1
    runtime_api.unassign.assert_called_once_with("vm-2")


@pytest.mark.asyncio
async def test_restart_rejects_unknown_accelerator(manager, runtime_api):
    await connected(manager)
    async with Client(build_server(manager, Path("oauth.json"))) as client:
        result = await client.call_tool(
            "restart_runtime",
            {
                "accelerator": "MAGIC",
                "notebook_id": "nb",
                "preservation_confirmed": True,
            },
        )
    assert result.structured_content["error"]["kind"] == "invalid_input"
    runtime_api.assign.assert_not_called()


@pytest.mark.asyncio
async def test_restart_switches_only_selected_assignment(manager, runtime_api):
    await connected(manager)
    async with Client(build_server(manager, Path("oauth.json"))) as client:
        result = await client.call_tool(
            "restart_runtime",
            {
                "accelerator": "T4",
                "notebook_id": "nb",
                "preservation_confirmed": True,
                "assignment_endpoint": "vm-1",
            },
        )
    assert result.structured_content["requested_accelerator"] == "T4"
    runtime_api.unassign.assert_called_once_with("vm-1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool", ["stop_runtime", "restart_runtime", "request_runtime_profile"]
)
async def test_api_backend_failure_is_structured(manager, runtime_api, tool):
    await connected(manager)
    runtime_api.list_assignments.side_effect = fail(
        "protocol_error", "runtime backend unavailable"
    )
    args = {
        "notebook_id": "nb",
        "preservation_confirmed": True,
        "assignment_endpoint": "vm-1",
    }
    if tool == "request_runtime_profile":
        args["profile"] = "debug-gpu"
    async with Client(build_server(manager, Path("oauth.json"))) as client:
        result = await client.call_tool(tool, args)
    assert result.structured_content["error"]["kind"] == "protocol_error"


@pytest.mark.asyncio
async def test_disconnect_closes_only_local_session(manager):
    await connected(manager)
    async with Client(build_server(manager)) as client:
        result = await client.call_tool("disconnect_runtime", {"notebook_id": "nb"})
    assert result.structured_content["runtime_stopped"] is False
    with pytest.raises(Exception):
        manager.get("nb")


@pytest.mark.asyncio
async def test_disconnect_backend_failure_is_structured(manager):
    session = await connected(manager)
    session.aclose = AsyncMock(side_effect=fail("protocol_error", "close failed"))
    async with Client(build_server(manager)) as client:
        result = await client.call_tool("disconnect_runtime", {"notebook_id": "nb"})
    assert result.structured_content["error"]["kind"] == "protocol_error"
