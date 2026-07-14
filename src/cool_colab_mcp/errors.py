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

"""The uniform structured-error contract every tool reuses (plan.md §3/§9)."""

from typing import Any, Literal

from fastmcp.tools.tool import ToolResult
from pydantic import BaseModel

from cool_colab_mcp.utils import json_tool_result

ErrorKind = Literal[
    "not_connected",
    "user_action_required",
    "unknown_notebook",
    "invalid_input",
    "protocol_error",
]


class StructuredError(BaseModel):
    """The one error shape every tool returns on failure."""

    kind: ErrorKind
    message: str
    details: dict[str, Any] | None = None

    def as_result(self) -> ToolResult:
        """Render as a tool result: {"error": {kind, message, details?}}."""
        return json_tool_result({"error": self.model_dump(exclude_none=True)})


class ToolFailed(Exception):
    """Aborts an operation with a StructuredError; tool handlers turn it into a result."""

    def __init__(self, error: StructuredError):
        super().__init__(error.message)
        self.error = error


def fail(kind: ErrorKind, message: str, **details: Any) -> ToolFailed:
    """Build a ToolFailed in one call: raise fail("invalid_input", "...", url=url)."""
    return ToolFailed(
        StructuredError(kind=kind, message=message, details=details or None)
    )
