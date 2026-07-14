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

"""OS-keyring storage for the Google OAuth token (plan.md §3).

Hardens the reference fork's plaintext token cache (`~/.colab-mcp-auth-token.json`
in SebastianGilPinzon/colab-mcp): the token lives only in the OS keyring and is
never written to disk, logged, or returned to connected agents.
"""

import json

import keyring
import keyring.errors
from google.oauth2.credentials import Credentials

from cool_colab_mcp.constants import (
    KEYRING_SERVICE,
    KEYRING_TOKEN_ACCOUNT,
    OAUTH_SCOPES,
)
from cool_colab_mcp.errors import ToolFailed, fail


def _keyring_unavailable() -> ToolFailed:
    return fail(
        "user_action_required",
        "The OS keyring is unavailable. Install or configure a keyring backend "
        "for this user, then retry authentication.",
    )


def store_token(credentials: Credentials) -> None:
    """Persist the OAuth token (including its refresh token) in the OS keyring."""
    try:
        keyring.set_password(
            KEYRING_SERVICE, KEYRING_TOKEN_ACCOUNT, credentials.to_json()
        )
    except keyring.errors.KeyringError:
        raise _keyring_unavailable() from None


def load_token() -> Credentials | None:
    """Load the cached OAuth token; None if absent or unreadable."""
    try:
        raw = keyring.get_password(KEYRING_SERVICE, KEYRING_TOKEN_ACCOUNT)
    except keyring.errors.KeyringError:
        raise _keyring_unavailable() from None
    if raw is None:
        return None
    try:
        info = json.loads(raw)
        return Credentials.from_authorized_user_info(info, scopes=list(OAUTH_SCOPES))
    except ValueError:
        return None


def delete_token() -> None:
    """Remove the cached OAuth token; deleting an absent token is a no-op."""
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_TOKEN_ACCOUNT)
    except keyring.errors.PasswordDeleteError:
        pass
    except keyring.errors.KeyringError:
        raise _keyring_unavailable() from None
