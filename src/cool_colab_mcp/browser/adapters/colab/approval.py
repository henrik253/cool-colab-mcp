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

"""Verified approval of Colab's "Connect to a local Colab MCP server" dialog (plan.md §11).

Colab's frontend cannot be made to connect without this dialog: its `connect-local-mcp`
command always awaits it, and it offers no "remember" option. So we click it — but only
after proving the dialog belongs to the session that opened it.
"""

from cool_colab_mcp.browser.adapters.colab.constants import (
    CONNECT_BUTTON,
    CONNECT_DIALOG_OPEN,
    DIALOG_STATE_ATTACHED,
    TOKEN_FIELD,
    TOKEN_FIELD_SEPARATOR,
)
from cool_colab_mcp.constants import COLAB, COLAB_ALT_DOMAIN
from cool_colab_mcp.errors import fail


async def await_connect_dialog(page, timeout_ms: int) -> None:
    """Wait for Colab to raise the MCP connect dialog."""
    try:
        await page.wait_for_selector(
            CONNECT_DIALOG_OPEN, state=DIALOG_STATE_ATTACHED, timeout=timeout_ms
        )
    except Exception as exc:
        raise fail(
            "user_action_required",
            "Colab did not show the 'Connect to a local Colab MCP server' dialog. "
            "The Colab UI may have changed, or the MCP integration may be unavailable "
            "for this account. Open the notebook tab and connect manually.",
        ) from exc


async def verify_dialog_belongs_to(page, token: str, port: int) -> None:
    """Refuse to click unless this dialog is ours (plan.md §11).

    Colab prefills the readonly token field with exactly "<token>&<port>", so the page
    itself proves which local server it is about to reach.
    """
    origin = await page.evaluate("location.origin")
    if origin not in (COLAB, COLAB_ALT_DOMAIN):
        raise fail(
            "invalid_input",
            f"Refusing to approve an MCP dialog on unexpected origin '{origin}'.",
            origin=origin,
        )

    shown = await page.locator(TOKEN_FIELD).get_attribute("value")
    expected = f"{token}{TOKEN_FIELD_SEPARATOR}{port}"
    if shown != expected:
        # Never log or return the token itself.
        raise fail(
            "invalid_input",
            "Refusing to approve: the dialog's token/port do not match this session. "
            "Another Colab tab may be requesting a different local server.",
            port=port,
        )


async def approve(page, token: str, port: int, timeout_ms: int) -> None:
    """Wait for the dialog, verify it is ours, then accept it.

    Returns once the button is clicked. The caller must treat the server-side
    connection as the only proof of success.
    """
    await await_connect_dialog(page, timeout_ms)
    await verify_dialog_belongs_to(page, token, port)
    await page.locator(CONNECT_BUTTON).click()
