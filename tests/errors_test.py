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

import json

import pytest
from pydantic import ValidationError

from cool_colab_mcp.errors import StructuredError, ToolFailed, fail


def test_as_result_carries_error_as_text_and_structured_content():
    error = StructuredError(kind="not_connected", message="no connection")
    result = error.as_result()

    expected = {"error": {"kind": "not_connected", "message": "no connection"}}
    assert result.structured_content == expected
    assert json.loads(result.content[0].text) == expected


def test_details_included_when_present():
    result = fail("unknown_notebook", "nope", notebook_id="nb-1").error.as_result()
    assert result.structured_content["error"]["details"] == {"notebook_id": "nb-1"}


def test_fail_builds_a_raisable_tool_failed():
    failure = fail("invalid_input", "bad url", url="x")
    assert isinstance(failure, ToolFailed)
    assert str(failure) == "bad url"
    assert failure.error.kind == "invalid_input"


def test_unknown_kind_rejected():
    with pytest.raises(ValidationError):
        StructuredError(kind="made_up", message="x")
