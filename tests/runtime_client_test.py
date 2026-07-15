"""Unit tests for the OAuth Colab runtime API boundary."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cool_colab_mcp.errors import ToolFailed
from cool_colab_mcp.runtime.client import RuntimeClient


def response(body: str, ok: bool = True, status: int = 200):
    return SimpleNamespace(text=body, ok=ok, status_code=status)


@pytest.fixture
def client(monkeypatch):
    session = Mock()
    monkeypatch.setattr(
        "cool_colab_mcp.runtime.client.AuthorizedSession", lambda credentials: session
    )
    return RuntimeClient(Mock()), session


def test_list_assignments_strips_xssi(client):
    runtime, session = client
    session.request.return_value = response(
        ')]}\'\n{"assignments":[{"endpoint":"vm-1"}]}'
    )
    assert runtime.list_assignments() == [{"endpoint": "vm-1"}]


def test_quota_denial_is_structured(client):
    runtime, session = client
    session.request.return_value = response(
        '{"outcome":"QUOTA_DENIED_REQUESTED_VARIANTS"}', ok=False, status=429
    )
    with pytest.raises(ToolFailed) as failure:
        runtime.assign("T4")
    assert failure.value.error.kind == "user_action_required"
    assert failure.value.error.details == {"outcome": "QUOTA_DENIED_REQUESTED_VARIANTS"}


def test_future_quota_denial_is_structured(client):
    runtime, session = client
    session.request.return_value = response(
        '{"outcome":"QUOTA_DENIED_FUTURE_REASON"}', ok=False, status=429
    )
    with pytest.raises(ToolFailed) as failure:
        runtime.assign("T4")
    assert failure.value.error.kind == "user_action_required"


@pytest.mark.parametrize("outcome", ["QUOTA_DENIED_REQUESTED_VARIANTS", "DENYLISTED"])
def test_403_recognized_policy_outcome_is_preserved(client, outcome):
    runtime, session = client
    session.request.return_value = response(
        json.dumps({"outcome": outcome, "message": "arbitrary private response"}),
        ok=False,
        status=403,
    )
    with pytest.raises(ToolFailed) as failure:
        runtime.list_assignments()
    assert failure.value.error.kind == "user_action_required"
    assert failure.value.error.details == {"outcome": outcome}
    assert "arbitrary" not in str(failure.value)
    assert "arbitrary" not in str(failure.value.error.details)


@pytest.mark.parametrize("status", [401, 403])
def test_auth_denial_is_actionable_without_body_leak(client, status):
    runtime, session = client
    session.request.return_value = response(
        '{"message":"sentinel-access-token-must-never-leak"}', ok=False, status=status
    )
    with pytest.raises(ToolFailed) as failure:
        runtime.list_assignments()
    assert failure.value.error.kind == "user_action_required"
    assert "sentinel" not in str(failure.value)
    assert "sentinel" not in str(failure.value.error.details)


@pytest.mark.parametrize("assignment", [None, {}, {"endpoint": ""}, {"endpoint": 4}])
def test_invalid_assignment_is_protocol_error(client, assignment):
    runtime, session = client
    session.request.return_value = response(json.dumps({"assignments": [assignment]}))
    with pytest.raises(ToolFailed) as failure:
        runtime.list_assignments()
    assert failure.value.error.kind == "protocol_error"


def test_transport_error_does_not_leak_credentials(client):
    runtime, session = client
    session.request.side_effect = RuntimeError("sentinel-access-token-must-never-leak")
    with pytest.raises(ToolFailed) as failure:
        runtime.list_assignments()
    assert failure.value.error.kind == "protocol_error"
    assert "sentinel" not in str(failure.value)


def test_unassign_uses_server_token(client):
    runtime, session = client
    session.request.side_effect = [response('{"token":"xsrf"}'), response("")]
    runtime.unassign("vm/1")
    assert (
        session.request.call_args_list[1].kwargs["headers"]["X-Goog-Colab-Token"]
        == "xsrf"
    )


def test_empty_unassign_endpoint_is_invalid_input(client):
    runtime, session = client
    with pytest.raises(ToolFailed) as failure:
        runtime.unassign("")
    assert failure.value.error.kind == "invalid_input"
    session.request.assert_not_called()
