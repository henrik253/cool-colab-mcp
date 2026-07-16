"""Strict approval of the Colab MCP connection dialog without page scripting."""

import asyncio
from typing import Any
from urllib.parse import parse_qs, urlsplit

from cool_colab_mcp.constants import (
    BROWSER_APPROVAL_ATTEMPTS,
    BROWSER_APPROVAL_TIMEOUT,
    BROWSER_RETRY_DELAY,
    COLAB,
    COLAB_MCP_APPROVE_BUTTON,
    COLAB_MCP_DIALOG_NAME,
    PROXY_PORT_PARAM,
    PROXY_TOKEN_PARAM,
)
from cool_colab_mcp.errors import fail


def verify_connection_page(
    page_url: str, notebook_url: str, token: str, port: int
) -> None:
    """Verify origin, notebook path, and exact session fragment before any click."""
    page = urlsplit(page_url)
    notebook = urlsplit(notebook_url)
    fragment = parse_qs(page.fragment)
    if (
        (page.scheme, page.netloc) != ("https", urlsplit(COLAB).netloc)
        or page.path != notebook.path
        or fragment.get(PROXY_TOKEN_PARAM) != [token]
        or fragment.get(PROXY_PORT_PARAM) != [str(port)]
    ):
        raise fail(
            "user_action_required",
            "Refused to approve an unverified Colab MCP connection. "
            "Close the tab and open the notebook again.",
        )


async def approve_mcp_connection(
    page: Any, notebook_url: str, token: str, port: int
) -> None:
    """Click only Continue inside the named Colab MCP dialog, with bounded retries."""
    verify_connection_page(page.url, notebook_url, token, port)
    dialog = page.get_by_role("dialog").filter(has_text=COLAB_MCP_DIALOG_NAME)
    button = dialog.get_by_role("button", name=COLAB_MCP_APPROVE_BUTTON, exact=True)
    for attempt in range(BROWSER_APPROVAL_ATTEMPTS):
        try:
            await button.click(timeout=BROWSER_APPROVAL_TIMEOUT * 1000)
            return
        except Exception:
            if attempt == BROWSER_APPROVAL_ATTEMPTS - 1:
                raise fail(
                    "user_action_required",
                    "The verified Colab MCP approval dialog was not found. "
                    "Colab may have changed its UI; approve the connection manually.",
                ) from None
            await asyncio.sleep(BROWSER_RETRY_DELAY)
