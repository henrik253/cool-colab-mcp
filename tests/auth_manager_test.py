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

"""Tests for the keyring token store (auth/manager.py)."""

import keyring
import keyring.errors
import pytest
from conftest import SENTINEL_TOKEN, make_credentials

from cool_colab_mcp.auth.manager import delete_token, load_token, store_token
from cool_colab_mcp.constants import KEYRING_SERVICE, KEYRING_TOKEN_ACCOUNT
from cool_colab_mcp.errors import ToolFailed


@pytest.mark.parametrize(
    "operation,keyring_method",
    [
        (lambda: store_token(make_credentials()), "set_password"),
        (load_token, "get_password"),
        (delete_token, "delete_password"),
    ],
)
def test_missing_keyring_backend_requires_user_action(
    monkeypatch, operation, keyring_method
):
    def unavailable(*args, **kwargs):
        raise keyring.errors.NoKeyringError("no backend")

    monkeypatch.setattr(keyring, keyring_method, unavailable)
    with pytest.raises(ToolFailed) as failure:
        operation()
    assert failure.value.error.kind == "user_action_required"
    assert "keyring" in failure.value.error.message.lower()


class TestStoreAndLoad:
    def test_roundtrip_preserves_token_and_refresh_token(self, fake_keyring):
        store_token(make_credentials())

        loaded = load_token()

        assert loaded is not None
        assert loaded.token == SENTINEL_TOKEN
        assert loaded.refresh_token == "test-refresh-token"

    def test_token_lives_under_the_configured_service_and_account(self, fake_keyring):
        store_token(make_credentials())
        assert (KEYRING_SERVICE, KEYRING_TOKEN_ACCOUNT) in fake_keyring

    def test_load_without_stored_token_returns_none(self, fake_keyring):
        assert load_token() is None

    def test_load_with_corrupt_entry_returns_none(self, fake_keyring):
        fake_keyring[(KEYRING_SERVICE, KEYRING_TOKEN_ACCOUNT)] = "not json"
        assert load_token() is None

    def test_load_with_incomplete_entry_returns_none(self, fake_keyring):
        fake_keyring[(KEYRING_SERVICE, KEYRING_TOKEN_ACCOUNT)] = "{}"
        assert load_token() is None


class TestDelete:
    def test_delete_removes_the_token(self, fake_keyring):
        store_token(make_credentials())
        delete_token()
        assert load_token() is None
        assert fake_keyring == {}

    def test_delete_without_stored_token_is_a_noop(self, fake_keyring):
        delete_token()
        assert fake_keyring == {}
