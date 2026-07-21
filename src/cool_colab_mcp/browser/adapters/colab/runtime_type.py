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

"""Drive Colab's "Change runtime type" dialog to bind a tab to an accelerator.

The OAuth runtime-assignment API reserves a Colab VM but registers it under a
private notebook hash; a freshly opened scratch tab never adopts it and connects
to a default CPU kernel instead. The only reliable way to put the *visible* tab
on a GPU is the frontend flow a user would click: open Change-runtime-type, pick
the accelerator, Save, then Connect. This module automates exactly that.
"""

from cool_colab_mcp.browser.adapters.colab.constants import (
    COMMAND_PALETTE_KEYS,
    CONNECT_RUNTIME_COMMAND,
    RUNTIME_TYPE_COMMAND,
    RUNTIME_TYPE_DIALOG,
    RUNTIME_TYPE_SAVE_BUTTON,
    RUNTIME_WARNING_OK_BUTTON,
    accelerator_radio_label,
)
from cool_colab_mcp.errors import fail

# Click a button by CSS selector in JS. A programmatic click ignores the pointer
# interception that a stacked confirmation dialog would otherwise cause, and
# returns whether the button was present.
_CLICK_SELECTOR_JS = """(sel) => {
  const el = document.querySelector(sel);
  if (el) { el.click(); return true; }
  return false;
}"""

# Pierce open shadow roots to click the accelerator radio by its aria-label; a
# plain selector cannot cross the colab-runtime-attributes-selector boundary.
_CLICK_RADIO_JS = """(label) => {
  const visit = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.tagName === 'INPUT' && el.getAttribute('aria-label') === label) {
        el.click();
        return true;
      }
      if (el.shadowRoot && visit(el.shadowRoot)) return true;
    }
    return false;
  };
  const dialog = document.querySelector('mwc-dialog.change-runtime-type');
  return dialog ? visit(dialog) : false;
}"""


async def _run_command(page, text: str) -> None:
    """Invoke a Colab command through the command palette."""
    await page.keyboard.press(COMMAND_PALETTE_KEYS)
    await page.wait_for_timeout(800)
    await page.keyboard.type(text, delay=30)
    await page.wait_for_timeout(1000)
    await page.keyboard.press("Enter")


async def select_accelerator(page, accelerator: str, timeout_ms: int) -> None:
    """Set this tab's runtime type to `accelerator` and start connecting.

    Leaves the kernel connecting in the background; the caller waits on its own
    connection signal. A no-op accelerator of NONE/CPU still normalises the tab
    to CPU so a stale GPU selection cannot linger.
    """
    label = accelerator_radio_label(accelerator)

    await _run_command(page, RUNTIME_TYPE_COMMAND)
    try:
        await page.wait_for_selector(
            f"{RUNTIME_TYPE_DIALOG}[open]", state="attached", timeout=timeout_ms
        )
    except Exception as exc:
        raise fail(
            "user_action_required",
            "Colab did not show the 'Change runtime type' dialog. The Colab UI may "
            "have changed; set the runtime type manually.",
        ) from exc

    # Radios render a frame after the dialog opens; retry the shadow-DOM click.
    clicked = False
    for _ in range(20):
        clicked = await page.evaluate(_CLICK_RADIO_JS, label)
        if clicked:
            break
        await page.wait_for_timeout(250)
    if not clicked:
        raise fail(
            "user_action_required",
            f"Could not find the '{label}' accelerator option in Change runtime "
            "type. Colab may not offer it for this account.",
        )

    await page.wait_for_timeout(300)
    # JS-click Save: on a connected notebook Colab stacks a confirmation warning
    # that would intercept a real pointer click on the button behind it.
    await page.evaluate(_CLICK_SELECTOR_JS, RUNTIME_TYPE_SAVE_BUTTON)
    await page.wait_for_timeout(1000)

    # Confirm the "changing runtime type disconnects the current runtime" warning
    # if Colab raised it (only appears when a runtime was already connected).
    for _ in range(8):
        if await page.evaluate(_CLICK_SELECTOR_JS, RUNTIME_WARNING_OK_BUTTON):
            break
        await page.wait_for_timeout(250)
    await page.wait_for_timeout(1500)

    # Saving a changed runtime type usually triggers a reconnect on its own, but
    # asking explicitly is harmless and covers the case where it does not.
    await _run_command(page, CONNECT_RUNTIME_COMMAND)
