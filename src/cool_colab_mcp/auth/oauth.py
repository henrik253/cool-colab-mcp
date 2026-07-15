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

"""OAuth flow for the Colab runtime API (plan.md §3, consumed by §8).

Scopes and the fixed local-server port follow the reference fork
SebastianGilPinzon/colab-mcp (Apache 2.0). Every path that needs interactive
consent raises a structured `user_action_required` error, and token values
never appear in messages, details, or logs.
"""

from pathlib import Path

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from cool_colab_mcp.auth.manager import delete_token, load_token, store_token
from cool_colab_mcp.constants import OAUTH_LOCAL_SERVER_PORT, OAUTH_SCOPES
from cool_colab_mcp.errors import ToolFailed, fail

_CONSENT_HINT = (
    "Run the interactive consent flow (cool_colab_mcp.auth.run_consent_flow) "
    "to sign in with Google in your browser; the token is then stored in the "
    "OS keyring."
)
_MISSING_CONFIG_HINT = (
    "Create an OAuth client of type 'Desktop app' in the Google Cloud Console, "
    "download its client-secrets JSON, and save it to the path above. Then run "
    "the interactive consent flow (cool_colab_mcp.auth.run_consent_flow)."
)


def ensure_credentials(oauth_config_path: Path) -> Credentials:
    """Return valid Google OAuth credentials from the keyring, refreshing if needed.

    Raises ToolFailed with kind `user_action_required` whenever the token is
    missing, unrefreshable, or interactive consent is needed.
    """
    credentials = load_token()
    if credentials is None:
        raise _consent_required(
            oauth_config_path, "No cached Google OAuth token was found."
        )
    if credentials.valid:
        return credentials
    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except GoogleAuthError:
            delete_token()
            raise _consent_required(
                oauth_config_path,
                "The cached Google OAuth token could not be refreshed "
                "(it may have expired or been revoked).",
            ) from None
        store_token(credentials)
        return credentials
    raise _consent_required(
        oauth_config_path,
        "The cached Google OAuth token is expired and has no refresh token.",
    )


def run_consent_flow(oauth_config_path: Path) -> Credentials:
    """Perform the interactive browser consent and store the token in the keyring."""
    if not oauth_config_path.is_file():
        raise _missing_config(oauth_config_path)
    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(oauth_config_path), scopes=list(OAUTH_SCOPES)
        )
    except ValueError:
        raise fail(
            "user_action_required",
            "The OAuth client-secrets file is malformed. Replace it with a valid "
            "Desktop app client-secrets JSON file and retry consent.",
            oauth_config_path=str(oauth_config_path),
        ) from None
    try:
        credentials = flow.run_local_server(port=OAUTH_LOCAL_SERVER_PORT)
    except Exception:
        raise fail(
            "user_action_required",
            "Google consent was not completed. Re-run the consent flow and "
            "approve access for this app in the browser.",
            oauth_config_path=str(oauth_config_path),
        ) from None
    store_token(credentials)
    return credentials


def _consent_required(oauth_config_path: Path, reason: str) -> ToolFailed:
    """A user_action_required failure telling the user how to restore auth."""
    if not oauth_config_path.is_file():
        return _missing_config(oauth_config_path, reason)
    return fail(
        "user_action_required",
        f"{reason} {_CONSENT_HINT}",
        oauth_config_path=str(oauth_config_path),
    )


def _missing_config(oauth_config_path: Path, reason: str | None = None) -> ToolFailed:
    prefix = f"{reason} " if reason else ""
    return fail(
        "user_action_required",
        f"{prefix}No OAuth client configuration was found at "
        f"{oauth_config_path}. {_MISSING_CONFIG_HINT}",
        oauth_config_path=str(oauth_config_path),
    )
