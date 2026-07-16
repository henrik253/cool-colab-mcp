"""Minimal OAuth client for Colab runtime assignment.

The request shape is adapted from SebastianGilPinzon/colab-mcp (Apache 2.0).
"""

import json
import uuid
from typing import Any
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials

from cool_colab_mcp.constants import (
    COLAB_CLIENT_AGENT,
    COLAB_AUTH_USER,
    COLAB_AUTH_USER_PARAM,
    COLAB_RUNTIME_API,
    RUNTIME_ASSIGN_PATH,
    RUNTIME_ASSIGNMENTS_PATH,
    RUNTIME_DENIAL_OUTCOMES,
    RUNTIME_UNASSIGN_PATH_PREFIX,
    XSSI_PREFIX,
)
from cool_colab_mcp.errors import fail


class RuntimeClient:
    def __init__(self, credentials: Credentials) -> None:
        self.session = AuthorizedSession(credentials)

    def list_assignments(self) -> list[dict[str, Any]]:
        body = self._request("GET", RUNTIME_ASSIGNMENTS_PATH)
        assignments = body.get("assignments", [])
        if not isinstance(assignments, list):
            raise fail("protocol_error", "Colab returned an invalid assignment list.")
        for assignment in assignments:
            if (
                not isinstance(assignment, dict)
                or not isinstance(assignment.get("endpoint"), str)
                or not assignment["endpoint"]
            ):
                raise fail(
                    "protocol_error", "Colab returned an invalid runtime assignment."
                )
        return assignments

    def unassign(self, endpoint: str) -> None:
        if not endpoint:
            raise fail("invalid_input", "assignment_endpoint must not be empty.")
        path = f"{RUNTIME_UNASSIGN_PATH_PREFIX}{quote(endpoint, safe='')}"
        token = self._request("GET", path).get("token")
        if not isinstance(token, str):
            raise fail("protocol_error", "Colab did not provide an unassignment token.")
        self._request("POST", path, headers={"X-Goog-Colab-Token": token})

    def assign(self, accelerator: str) -> dict[str, Any]:
        notebook_hash = str(uuid.uuid4()).replace("-", "_") + "." * 8
        variant = (
            "DEFAULT"
            if accelerator == "NONE"
            else ("TPU" if accelerator.startswith("V") else "GPU")
        )
        params = {"nbh": notebook_hash, "variant": variant, "accelerator": accelerator}
        initial = self._request("GET", RUNTIME_ASSIGN_PATH, params=params)
        if "endpoint" in initial:
            return initial
        token = initial.get("token")
        if not isinstance(token, str):
            raise fail(
                "protocol_error", "Colab did not provide a runtime assignment token."
            )
        return self._request(
            "POST",
            RUNTIME_ASSIGN_PATH,
            params=params,
            headers={"X-Goog-Colab-Token": token},
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "X-Goog-Colab-Client-Agent": COLAB_CLIENT_AGENT,
            **kwargs.pop("headers", {}),
        }
        params = {
            COLAB_AUTH_USER_PARAM: COLAB_AUTH_USER,
            **kwargs.pop("params", {}),
        }
        try:
            response = self.session.request(
                method,
                f"{COLAB_RUNTIME_API}{path}",
                headers=headers,
                params=params,
                **kwargs,
            )
        except Exception:
            raise fail(
                "protocol_error",
                "The Colab runtime API could not be reached. Retry later.",
            ) from None
        text = response.text.removeprefix(XSSI_PREFIX)
        try:
            body = json.loads(text) if text else {}
        except json.JSONDecodeError:
            body = None
        outcome = body.get("outcome") if isinstance(body, dict) else None
        denied = isinstance(outcome, str) and (
            outcome.startswith("QUOTA_DENIED") or outcome in RUNTIME_DENIAL_OUTCOMES
        )
        if denied:
            raise fail(
                "user_action_required",
                "Colab denied the runtime request because of quota or account policy.",
                outcome=outcome,
            )
        if response.status_code in (401, 403):
            raise fail(
                "user_action_required",
                "Colab rejected runtime authorization. Reauthenticate or grant the "
                "required Colab OAuth consent, then retry.",
                status_code=response.status_code,
            )
        if body is None:
            raise fail(
                "protocol_error", "Colab returned an invalid runtime response."
            ) from None
        if not response.ok:
            raise fail(
                "protocol_error",
                "The Colab runtime API rejected the request.",
                status_code=response.status_code,
            )
        if not isinstance(body, dict):
            raise fail("protocol_error", "Colab returned an invalid runtime response.")
        return body
