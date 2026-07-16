# Copyright 2026 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""FastMCP tools for direct runtime file transfer."""

from fastmcp import FastMCP
from fastmcp.tools.tool import ToolResult

from cool_colab_mcp.constants import RUNTIME_ROOT
from cool_colab_mcp.errors import ToolFailed
from cool_colab_mcp.sessions.manager import SessionManager
from cool_colab_mcp.transfers import UploadManager
from cool_colab_mcp.utils import json_tool_result


def register_transfer_tools(mcp: FastMCP, sessions: SessionManager) -> None:
    uploads = UploadManager()

    @mcp.tool
    async def upload_file(
        source: str,
        destination: str | None = None,
        notebook_id: str | None = None,
        upload_id: str | None = None,
    ) -> ToolResult:
        """Upload one allowed host file into /content using chunked code execution.

        Set upload_id when another concurrent client needs to query or cancel this
        transfer while the call is running; otherwise an id is generated.
        """
        try:
            status = await uploads.upload_file(
                sessions.get(notebook_id), source, destination, upload_id
            )
            return json_tool_result(status.model_dump(exclude_none=True))
        except ToolFailed as failure:
            return failure.error.as_result()

    @mcp.tool
    async def upload_directory(
        source: str, destination: str | None = None, notebook_id: str | None = None
    ) -> ToolResult:
        """Recursively upload an allowed host directory into /content."""
        try:
            statuses = await uploads.upload_directory(
                sessions.get(notebook_id), source, destination
            )
            return json_tool_result(
                {"uploads": [item.model_dump(exclude_none=True) for item in statuses]}
            )
        except ToolFailed as failure:
            return failure.error.as_result()

    @mcp.tool
    async def get_upload_status(upload_id: str) -> ToolResult:
        """Return progress and verification state for an upload in this process."""
        try:
            return json_tool_result(
                uploads.status(upload_id).model_dump(exclude_none=True)
            )
        except ToolFailed as failure:
            return failure.error.as_result()

    @mcp.tool
    async def cancel_upload(upload_id: str) -> ToolResult:
        """Request cancellation and cleanup of an active upload."""
        try:
            return json_tool_result(
                uploads.cancel(upload_id).model_dump(exclude_none=True)
            )
        except ToolFailed as failure:
            return failure.error.as_result()

    @mcp.tool
    async def list_runtime_files(
        path: str = RUNTIME_ROOT, notebook_id: str | None = None
    ) -> ToolResult:
        """List files below a /content path in the selected runtime."""
        try:
            files = await uploads.list_runtime_files(sessions.get(notebook_id), path)
            return json_tool_result({"files": files})
        except ToolFailed as failure:
            return failure.error.as_result()
