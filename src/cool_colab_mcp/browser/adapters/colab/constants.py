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

"""Colab UI surface for the MCP connect dialog (plan.md §11).

Everything Colab's frontend could rename lives here and nowhere else, so a Colab UI
change never reaches the session, registry, or transfer layers (plan.md §14).
"""

# The dialog Colab auto-raises when our #mcpProxyToken fragment is present. Its host
# element carries no layout box (the surface is in its shadow root), so wait for it in
# the "attached" state — never for visibility.
CONNECT_DIALOG = "mwc-dialog.local-mcp-connect-dialog"
CONNECT_DIALOG_OPEN = f"{CONNECT_DIALOG}[open]"

# Readonly, prefilled by Colab from our fragment with exactly "<token>&<port>".
# This is the verification signal required by plan.md §11.
TOKEN_FIELD = "colab-local-mcp-connect-dialog #token-field"
TOKEN_FIELD_SEPARATOR = "&"

CONNECT_BUTTON = f'{CONNECT_DIALOG} md-text-button[dialogaction="ok"]'

DIALOG_STATE_ATTACHED = "attached"

# Change-runtime-type dialog. Like the connect dialog, its host mwc-dialog has no
# layout box, and the accelerator radios live inside nested shadow roots (the
# colab-runtime-attributes-selector component), so they are reached by piercing
# shadow DOM in JS rather than by a plain Playwright selector.
RUNTIME_TYPE_DIALOG = "mwc-dialog.change-runtime-type"
RUNTIME_TYPE_SAVE_BUTTON = f'{RUNTIME_TYPE_DIALOG} md-text-button[dialogaction="ok"]'
# Switching runtime type on a *connected* notebook raises a confirmation warning
# ("changing this disconnects the current runtime"). Its OK button and the Save
# button both use dialogaction="ok", so each is scoped to its own dialog class.
RUNTIME_WARNING_DIALOG = "mwc-dialog.dismiss-runtime-warning"
RUNTIME_WARNING_OK_BUTTON = (
    f'{RUNTIME_WARNING_DIALOG} md-text-button[dialogaction="ok"]'
)
# Colab labels the accelerator radios "CPU", "T4 GPU", "L4 GPU", "A100 GPU", ...
# The command palette entry that opens the dialog, and the one that connects.
RUNTIME_TYPE_COMMAND = "Change runtime type"
CONNECT_RUNTIME_COMMAND = "Connect to a hosted runtime"
COMMAND_PALETTE_KEYS = "Control+Shift+P"


def accelerator_radio_label(accelerator: str) -> str:
    """Map an internal accelerator name to the dialog's radio aria-label."""
    return "CPU" if accelerator in ("NONE", "CPU") else f"{accelerator} GPU"
