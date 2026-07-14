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

"""Persistent authentication: keyring token storage and the OAuth flow (plan.md §3)."""

from cool_colab_mcp.auth.manager import delete_token, load_token, store_token
from cool_colab_mcp.auth.oauth import ensure_credentials, run_consent_flow

__all__ = [
    "delete_token",
    "ensure_credentials",
    "load_token",
    "run_consent_flow",
    "store_token",
]
