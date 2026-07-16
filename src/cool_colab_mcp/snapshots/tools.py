"""Snapshot MCP tools."""

from typing import Any

from fastmcp import FastMCP
from fastmcp.tools.tool import ToolResult

from cool_colab_mcp.constants import (
    ADD_CODE_CELL,
    ADD_TEXT_CELL,
    DELETE_CELL,
    DEFAULT_CODE_LANGUAGE,
    DEFAULT_NOTEBOOK_ID,
    GET_CELLS,
)
from cool_colab_mcp.errors import ToolFailed, fail
from cool_colab_mcp.sessions.manager import SessionManager
from cool_colab_mcp.sessions.session import NotebookSession
from cool_colab_mcp.snapshots.manager import (
    RecoveryMetadata,
    SnapshotManager,
    notebook_document,
)
from cool_colab_mcp.utils import json_tool_result


def _cells(payload: dict[str, Any]) -> Any:
    return payload.get("cells", payload)


async def capture_document(session: NotebookSession) -> dict[str, Any]:
    result = await session.call_tool(GET_CELLS, {})
    if result.structured_content is None:
        raise fail("protocol_error", "get_cells returned no structured notebook data.")
    return notebook_document(
        session.merge_cached_outputs(_cells(result.structured_content))
    )


async def restore_document(session: NotebookSession, document: dict[str, Any]) -> None:
    session.cell_outputs.clear()
    current = await session.call_tool(GET_CELLS, {})
    current_cells = _cells(current.structured_content or {})
    if not isinstance(current_cells, list):
        raise fail("protocol_error", "get_cells returned an unexpected payload.")
    for cell in reversed(current_cells):
        cell_id = cell.get("id", cell.get("cellId"))
        if not isinstance(cell_id, str):
            raise fail("protocol_error", "get_cells returned a cell without an id.")
        await session.call_tool(DELETE_CELL, {"cellId": cell_id})
    for index, cell in enumerate(document["cells"]):
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(source)
        tool = ADD_TEXT_CELL if cell.get("cell_type") == "markdown" else ADD_CODE_CELL
        key = "content" if tool == ADD_TEXT_CELL else "code"
        args = {key: source, "cellIndex": index}
        if tool == ADD_CODE_CELL:
            args["language"] = DEFAULT_CODE_LANGUAGE
        await session.call_tool(tool, args)


def register_snapshot_tools(mcp: FastMCP, sessions: SessionManager) -> None:
    snapshots = SnapshotManager()

    async def capture(
        notebook_id: str | None, recovery: RecoveryMetadata | None = None
    ) -> tuple[str, dict[str, Any]]:
        session = sessions.get(notebook_id)
        result = await session.call_tool(GET_CELLS, {})
        if result.structured_content is None:
            raise fail(
                "protocol_error", "get_cells returned no structured notebook data."
            )
        return session.notebook_id, notebook_document(
            session.merge_cached_outputs(_cells(result.structured_content)), recovery
        )

    @mcp.tool
    async def create_snapshot(
        notebook_id: str | None = None,
        environment_setup_instructions: list[str] | None = None,
        git_repository: str | None = None,
        git_commit: str | None = None,
        checkpoint_paths: list[str] | None = None,
        artifact_paths: list[str] | None = None,
    ) -> ToolResult:
        """Save the current notebook cells, metadata, and available outputs as a
        persistent, valid .ipynb snapshot."""
        try:
            recovery = RecoveryMetadata(
                environment_setup_instructions=environment_setup_instructions or [],
                git_repository=git_repository,
                git_commit=git_commit,
                checkpoint_paths=checkpoint_paths or [],
                artifact_paths=artifact_paths or [],
            )
            resolved_id, document = await capture(notebook_id, recovery)
            info = snapshots.create(resolved_id, document)
        except ToolFailed as failure:
            return failure.error.as_result()
        return json_tool_result({"notebook_id": resolved_id, "snapshot": info})

    @mcp.tool
    async def list_snapshots(notebook_id: str | None = None) -> ToolResult:
        """List persistent snapshots for a notebook session."""
        resolved_id = notebook_id or DEFAULT_NOTEBOOK_ID
        if notebook_id == "":
            return fail(
                "invalid_input", "notebook_id cannot be empty."
            ).error.as_result()
        try:
            listed = snapshots.list(resolved_id)
        except ToolFailed as failure:
            return failure.error.as_result()
        return json_tool_result({"notebook_id": resolved_id, "snapshots": listed})

    @mcp.tool
    async def restore_snapshot(
        snapshot_id: str, notebook_id: str | None = None
    ) -> ToolResult:
        """Replace the current notebook cells with a saved snapshot. Cell outputs
        remain preserved in the .ipynb file but cannot be injected by Colab's editor API."""
        try:
            session = sessions.get(notebook_id)
            document = snapshots.load(session.notebook_id, snapshot_id)
            await restore_document(session, document)
        except ToolFailed as failure:
            return failure.error.as_result()
        return json_tool_result(
            {"notebook_id": session.notebook_id, "restored": snapshot_id}
        )

    @mcp.tool
    async def export_notebook(
        destination: str, notebook_id: str | None = None
    ) -> ToolResult:
        """Export the current notebook as a valid .ipynb file on the MCP host."""
        try:
            resolved_id, document = await capture(notebook_id)
            path = snapshots.export(document, destination)
        except ToolFailed as failure:
            return failure.error.as_result()
        return json_tool_result({"notebook_id": resolved_id, "path": str(path)})
