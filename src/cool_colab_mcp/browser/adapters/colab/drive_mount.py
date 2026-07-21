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

"""Auto-approval of the Google Drive mount flow (Colab dialog + OAuth popup).

When a cell calls `drive.mount(...)`, Colab raises an in-page permission dialog
("This notebook is requesting access to your Google Drive files"), and accepting
it opens a real popup window on accounts.google.com with one or more consent
screens. Once consent is granted, later mounts in the session show neither
surface — so this module is a *watcher*: it approves each surface if and when it
appears, and stays idle otherwise. `drive.mount` itself times out after about
two minutes, which is why a human-speed manual flow often fails on servers and
the approval has to be automated.

Granting this consent lets notebook code read and modify all of the user's
Drive files, so the watcher only ever runs when the operator explicitly opted
in (the demo's --auto-drive flag / BrowserController(auto_drive=True)).

Verified UI contracts (2026-07-21, live probe):
- The Colab dialog is a *generic* `mwc-dialog.yes-no-dialog` — unlike the MCP
  connect dialog it has no distinctive class, so it is identified by its
  "Google Drive" text. Confirm button: `[dialogaction="ok"]`.
- Popup consent screens are locale-dependent in text ("Weiter"/"Continue") but
  structurally stable: footer buttons carry `jsname="LgbsSe"` with Cancel first
  and Confirm last in DOM order; `jsname="NakZHc"` is a scroll-down affordance
  that must be dismissed before the footer becomes reachable.
- The popup closes itself when consent completes; that close is the success
  signal, never the click.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

OAUTH_POPUP_HOST = "accounts.google.com"

# Poll cadence and bounds for one watch pass.
_POLL_S = 1.0
_MAX_POPUP_STEPS = 10
_POPUP_STEP_S = 2.0

# Approve the Colab Drive permission dialog if it is open. JS click: stacked
# dialogs intercept real pointer events (same lesson as the runtime-type flow).
_CLICK_DRIVE_DIALOG_JS = """() => {
  for (const d of document.querySelectorAll('mwc-dialog[open]')) {
    if ((d.textContent || '').includes('Google Drive')) {
      const ok = d.querySelector(
        'md-text-button[dialogaction="ok"], mwc-button[dialogaction="ok"]');
      if (ok) { ok.click(); return true; }
    }
  }
  return false;
}"""

# One consent-screen step: dismiss the scroll affordance, then click the last
# enabled footer button (Cancel precedes Confirm in DOM order, in every locale).
_POPUP_STEP_JS = """() => {
  const scroll = document.querySelector('button[jsname="NakZHc"]');
  if (scroll) scroll.click();
  const btns = Array.from(document.querySelectorAll('button[jsname="LgbsSe"]'))
    .filter(b => !b.disabled);
  if (!btns.length) return false;
  btns[btns.length - 1].click();
  return true;
}"""


def _is_oauth_popup(page) -> bool:
    try:
        return OAUTH_POPUP_HOST in page.url
    except Exception:
        return False


async def _step_through_popup(popup) -> None:
    """Click consent screens until the popup closes itself (or we give up)."""
    for step in range(_MAX_POPUP_STEPS):
        if popup.is_closed():
            logger.info("drive consent popup closed after %d steps", step)
            return
        try:
            await popup.evaluate(_POPUP_STEP_JS)
        except Exception:
            # The popup navigates or closes between screens; both are normal.
            pass
        await asyncio.sleep(_POPUP_STEP_S)
    logger.warning("drive consent popup did not close after %d steps", _MAX_POPUP_STEPS)


async def watch(page, context) -> None:
    """Approve Drive dialogs/popups for `page` until it closes or we are cancelled.

    Runs as a background task per managed tab. Idles at one poll per second;
    every surface is optional because an already-consented account shows none.
    """
    while not page.is_closed():
        try:
            if await page.evaluate(_CLICK_DRIVE_DIALOG_JS):
                logger.info("approved Colab Drive permission dialog")
        except Exception:
            # Page navigating; try again next tick.
            pass
        for candidate in context.pages:
            if candidate is not page and _is_oauth_popup(candidate):
                logger.info("stepping through Drive consent popup")
                await _step_through_popup(candidate)
        await asyncio.sleep(_POLL_S)
