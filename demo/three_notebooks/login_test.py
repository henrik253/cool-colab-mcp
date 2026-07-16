"""Sign-in detection for the managed browser. No browser, no network."""

from unittest.mock import AsyncMock, Mock

import pytest

from constants import APP_READY_MARKERS, SIGN_IN_MARKER
from run_demo import signed_in

SHELL = " ".join(APP_READY_MARKERS)


def page_showing(text: str):
    return Mock(evaluate=AsyncMock(return_value=text))


class TestSignedIn:
    @pytest.mark.asyncio
    async def test_rendered_shell_without_sign_in_prompt_is_signed_in(self):
        assert await signed_in(page_showing(f"scratchpad File {SHELL} Share"))

    @pytest.mark.asyncio
    async def test_rendered_shell_with_sign_in_prompt_is_signed_out(self):
        page = page_showing(f"scratchpad File {SHELL} {SIGN_IN_MARKER}")
        assert not await signed_in(page)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", ["", "   ", "Loading..."])
    async def test_unrendered_page_is_never_reported_as_signed_in(self, text):
        # Regression: an empty body trivially lacks SIGN_IN_MARKER, which used to be
        # read as success and closed the window before the operator could sign in.
        assert not await signed_in(page_showing(text))
