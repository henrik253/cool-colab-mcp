"""FastMCP tools for runtime status and lifecycle operations."""

from collections.abc import Awaitable
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.tools.tool import ToolResult

from cool_colab_mcp.auth.oauth import ensure_credentials
from cool_colab_mcp.constants import (
    RUNTIME_ACCELERATORS,
    RUNTIME_MANIFEST_CODE,
    RUNTIME_PROFILES,
    RUNTIME_STATUS_CODE,
)
from cool_colab_mcp.errors import ToolFailed, fail
from cool_colab_mcp.runtime.client import RuntimeClient
from cool_colab_mcp.sessions.manager import SessionManager
from cool_colab_mcp.utils import json_tool_result


def register_runtime_tools(
    mcp: FastMCP, manager: SessionManager, oauth_config_path: Path | None
) -> None:
    def api() -> RuntimeClient:
        if oauth_config_path is None:
            raise fail(
                "user_action_required",
                "Runtime switching needs an OAuth client configuration. Restart "
                "with --client-oauth-config PATH.",
            )
        return RuntimeClient(ensure_credentials(oauth_config_path))

    async def preserve(
        notebook_id: str | None, preservation_confirmed: bool
    ) -> dict[str, object]:
        if not preservation_confirmed:
            raise fail(
                "user_action_required",
                "Save the notebook, create a snapshot, and preserve selected logs and "
                "checkpoints before replacing the runtime. Then retry with "
                "preservation_confirmed=true. Automatic orchestration lands in Phase 2.",
            )
        current = manager.get(notebook_id)
        manifest = await current.run_code(RUNTIME_MANIFEST_CODE)
        return {
            "external_preservation_confirmed_by_caller": True,
            "manifest_generated": True,
            "manifest": manifest,
        }

    def release_target(client: RuntimeClient, assignment_endpoint: str | None) -> int:
        assignments = client.list_assignments()
        endpoints = [assignment["endpoint"] for assignment in assignments]
        if assignment_endpoint is None:
            raise fail(
                "user_action_required",
                "Cool Colab MCP cannot safely infer which account runtime belongs to "
                "this notebook. Choose its assignment_endpoint and retry; no runtime "
                "was released.",
                assignment_endpoints=endpoints,
            )
        if assignment_endpoint not in endpoints:
            raise fail(
                "invalid_input",
                "The selected assignment_endpoint is not a current Colab assignment.",
                assignment_endpoint=assignment_endpoint,
            )
        client.unassign(assignment_endpoint)
        return 1

    async def guarded(operation: Awaitable[ToolResult]) -> ToolResult:
        try:
            return await operation
        except ToolFailed as failure:
            return failure.error.as_result()

    async def status_result(notebook_id: str | None) -> ToolResult:
        current = manager.get(notebook_id)
        return json_tool_result(
            {
                "notebook_id": current.notebook_id,
                "runtime": await current.run_code(RUNTIME_STATUS_CODE),
            }
        )

    @mcp.tool
    async def get_runtime_status(notebook_id: str | None = None) -> ToolResult:
        """Inspect the connected notebook's actual CPU/GPU hardware."""
        return await guarded(status_result(notebook_id))

    @mcp.tool
    async def connect_runtime(notebook_id: str | None = None) -> ToolResult:
        """Verify a browser-connected notebook runtime and report its hardware."""
        return await guarded(status_result(notebook_id))

    @mcp.tool
    async def disconnect_runtime(notebook_id: str | None = None) -> ToolResult:
        """Disconnect the local notebook session without deleting its Colab VM."""

        async def operation():
            current = manager.get(notebook_id)
            key = current.notebook_id
            await manager.close(notebook_id)
            return json_tool_result(
                {"notebook_id": key, "disconnected": True, "runtime_stopped": False}
            )

        return await guarded(operation())

    @mcp.tool
    async def stop_runtime(
        notebook_id: str | None = None,
        preservation_confirmed: bool = False,
        assignment_endpoint: str | None = None,
    ) -> ToolResult:
        """Confirm external preservation, generate a manifest, then release one runtime."""

        async def operation():
            client = api()
            preservation = await preserve(notebook_id, preservation_confirmed)
            released = release_target(client, assignment_endpoint)
            return json_tool_result(
                {
                    "stopped": True,
                    "released": released,
                    "preservation": preservation,
                }
            )

        return await guarded(operation())

    @mcp.tool
    async def restart_runtime(
        accelerator: str = "NONE",
        notebook_id: str | None = None,
        preservation_confirmed: bool = False,
        assignment_endpoint: str | None = None,
    ) -> ToolResult:
        """Preserve current state, release the runtime, and request a replacement."""
        return await _switch(
            accelerator, notebook_id, preservation_confirmed, assignment_endpoint
        )

    @mcp.tool
    async def request_runtime_profile(
        profile: str,
        notebook_id: str | None = None,
        preservation_confirmed: bool = False,
        assignment_endpoint: str | None = None,
    ) -> ToolResult:
        """Request prototype-cpu, debug-gpu, or training-gpu through the OAuth API."""
        accelerator = RUNTIME_PROFILES.get(profile)
        if accelerator is None:
            return fail(
                "invalid_input",
                f"Unknown runtime profile '{profile}'.",
                allowed_profiles=sorted(RUNTIME_PROFILES),
            ).error.as_result()
        return await _switch(
            accelerator,
            notebook_id,
            preservation_confirmed,
            assignment_endpoint,
            profile,
        )

    async def _switch(
        accelerator: str,
        notebook_id: str | None,
        preservation_confirmed: bool,
        assignment_endpoint: str | None,
        profile: str | None = None,
    ) -> ToolResult:
        async def operation():
            if accelerator not in RUNTIME_ACCELERATORS:
                raise fail(
                    "invalid_input",
                    f"Unsupported accelerator '{accelerator}'.",
                    allowed_accelerators=list(RUNTIME_ACCELERATORS),
                )
            client = api()
            preservation = await preserve(notebook_id, preservation_confirmed)
            release_target(client, assignment_endpoint)
            assigned = client.assign(accelerator)
            return json_tool_result(
                {
                    "requested_profile": profile,
                    "requested_accelerator": accelerator,
                    "assignment": {
                        k: assigned[k]
                        for k in ("accelerator", "variant", "outcome")
                        if k in assigned
                    },
                    "preservation": preservation,
                    "reconnect_required": True,
                    "restore": "Reconnect, verify hardware with connect_runtime, then restore the snapshot/checkpoint. Automated restore lands in Phase 2.",
                }
            )

        return await guarded(operation())
