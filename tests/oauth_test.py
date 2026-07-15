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

"""Tests for the OAuth flow (auth/oauth.py)."""

import json
import logging
from datetime import timedelta
from unittest.mock import Mock

import pytest
from conftest import SENTINEL_TOKEN, make_credentials
from google.auth.exceptions import RefreshError, TransportError
from google.oauth2.credentials import Credentials

from cool_colab_mcp.auth.manager import load_token, store_token
from cool_colab_mcp.auth.oauth import ensure_credentials, run_consent_flow
from cool_colab_mcp.constants import OAUTH_LOCAL_SERVER_PORT
from cool_colab_mcp.errors import ToolFailed


@pytest.fixture
def config_file(tmp_path):
    """A fake OAuth client-secrets file on disk."""
    path = tmp_path / "oauth-client.json"
    path.write_text(json.dumps({"installed": {"client_id": "x", "client_secret": "y"}}))
    return path


def assert_user_action_required(exc_info, *fragments: str):
    error = exc_info.value.error
    assert error.kind == "user_action_required"
    for fragment in fragments:
        assert fragment in error.message


class TestEnsureCredentials:
    def test_valid_cached_token_is_returned(self, fake_keyring, config_file):
        store_token(make_credentials(expires_in=timedelta(hours=1)))

        credentials = ensure_credentials(config_file)

        assert credentials.valid
        assert credentials.token == SENTINEL_TOKEN

    def test_expired_token_is_refreshed_and_persisted(
        self, fake_keyring, config_file, monkeypatch
    ):
        store_token(make_credentials(expires_in=timedelta(hours=-1)))

        def fake_refresh(self, request):
            self.token = "refreshed-token"
            self.expiry = None

        monkeypatch.setattr(Credentials, "refresh", fake_refresh)

        credentials = ensure_credentials(config_file)

        assert credentials.token == "refreshed-token"
        assert load_token().token == "refreshed-token"

    def test_missing_token_requires_consent(self, fake_keyring, config_file):
        with pytest.raises(ToolFailed) as exc_info:
            ensure_credentials(config_file)
        assert_user_action_required(exc_info, "consent")

    def test_missing_token_and_config_names_the_config_path(
        self, fake_keyring, tmp_path
    ):
        missing = tmp_path / "does-not-exist.json"
        with pytest.raises(ToolFailed) as exc_info:
            ensure_credentials(missing)
        assert_user_action_required(exc_info, str(missing), "Google Cloud Console")

    def test_failed_refresh_requires_consent_and_clears_the_token(
        self, fake_keyring, config_file, monkeypatch
    ):
        store_token(make_credentials(expires_in=timedelta(hours=-1)))

        def failing_refresh(self, request):
            raise RefreshError("invalid_grant")

        monkeypatch.setattr(Credentials, "refresh", failing_refresh)

        with pytest.raises(ToolFailed) as exc_info:
            ensure_credentials(config_file)

        assert_user_action_required(exc_info, "consent")
        assert fake_keyring == {}

    def test_expired_token_without_refresh_token_requires_consent(
        self, fake_keyring, config_file
    ):
        store_token(
            make_credentials(refresh_token=None, expires_in=timedelta(hours=-1))
        )
        with pytest.raises(ToolFailed) as exc_info:
            ensure_credentials(config_file)
        assert_user_action_required(exc_info, "consent")


class TestRunConsentFlow:
    @pytest.fixture
    def fake_flow(self, monkeypatch):
        flow = Mock()
        flow.run_local_server.return_value = make_credentials(token="consented-token")
        monkeypatch.setattr(
            "cool_colab_mcp.auth.oauth.InstalledAppFlow",
            Mock(from_client_secrets_file=Mock(return_value=flow)),
        )
        return flow

    def test_consent_stores_the_token(self, fake_keyring, config_file, fake_flow):
        credentials = run_consent_flow(config_file)

        assert credentials.token == "consented-token"
        assert load_token().token == "consented-token"

    def test_consent_uses_the_reference_fork_port(
        self, fake_keyring, config_file, fake_flow
    ):
        run_consent_flow(config_file)
        fake_flow.run_local_server.assert_called_once_with(port=OAUTH_LOCAL_SERVER_PORT)

    def test_missing_config_requires_user_action(self, fake_keyring, tmp_path):
        missing = tmp_path / "does-not-exist.json"
        with pytest.raises(ToolFailed) as exc_info:
            run_consent_flow(missing)
        assert_user_action_required(exc_info, str(missing), "Google Cloud Console")

    def test_malformed_config_requires_user_action(
        self, fake_keyring, config_file, monkeypatch
    ):
        monkeypatch.setattr(
            "cool_colab_mcp.auth.oauth.InstalledAppFlow.from_client_secrets_file",
            Mock(side_effect=ValueError("invalid client secrets")),
        )
        with pytest.raises(ToolFailed) as exc_info:
            run_consent_flow(config_file)
        assert_user_action_required(exc_info, "malformed", "client-secrets")

    def test_declined_consent_requires_user_action_and_stores_nothing(
        self, fake_keyring, config_file, fake_flow
    ):
        fake_flow.run_local_server.side_effect = Exception("access_denied")

        with pytest.raises(ToolFailed) as exc_info:
            run_consent_flow(config_file)

        assert_user_action_required(exc_info, "consent")
        assert fake_keyring == {}


class TestNoTokenLeakage:
    """Plan.md §3: token values must never surface in logs, messages, or details."""

    def assert_no_leak(self, caplog, exc_info=None):
        assert SENTINEL_TOKEN not in caplog.text
        if exc_info is not None:
            error = exc_info.value.error
            assert SENTINEL_TOKEN not in str(exc_info.value)
            assert SENTINEL_TOKEN not in error.message
            assert SENTINEL_TOKEN not in json.dumps(error.details or {})
            assert exc_info.value.__cause__ is None
            assert exc_info.value.__suppress_context__

    def test_happy_path_logs_no_token(self, fake_keyring, config_file, caplog):
        caplog.set_level(logging.DEBUG)
        store_token(make_credentials(expires_in=timedelta(hours=1)))

        ensure_credentials(config_file)

        self.assert_no_leak(caplog)

    def test_leaky_refresh_error_is_not_propagated(
        self, fake_keyring, config_file, monkeypatch, caplog
    ):
        caplog.set_level(logging.DEBUG)
        store_token(make_credentials(expires_in=timedelta(hours=-1)))

        def leaky_refresh(self, request):
            raise RefreshError(f"invalid_grant: {SENTINEL_TOKEN}")

        monkeypatch.setattr(Credentials, "refresh", leaky_refresh)

        with pytest.raises(ToolFailed) as exc_info:
            ensure_credentials(config_file)

        self.assert_no_leak(caplog, exc_info)

    def test_leaky_transport_error_is_not_propagated(
        self, fake_keyring, config_file, monkeypatch, caplog
    ):
        caplog.set_level(logging.DEBUG)
        store_token(make_credentials(expires_in=timedelta(hours=-1)))

        def leaky_refresh(self, request):
            raise TransportError(f"network failed: {SENTINEL_TOKEN}")

        monkeypatch.setattr(Credentials, "refresh", leaky_refresh)

        with pytest.raises(ToolFailed) as exc_info:
            ensure_credentials(config_file)

        self.assert_no_leak(caplog, exc_info)

    def test_leaky_consent_error_is_not_propagated(
        self, fake_keyring, config_file, monkeypatch, caplog
    ):
        caplog.set_level(logging.DEBUG)
        flow = Mock()
        flow.run_local_server.side_effect = Exception(f"boom: {SENTINEL_TOKEN}")
        monkeypatch.setattr(
            "cool_colab_mcp.auth.oauth.InstalledAppFlow",
            Mock(from_client_secrets_file=Mock(return_value=flow)),
        )

        with pytest.raises(ToolFailed) as exc_info:
            run_consent_flow(config_file)

        self.assert_no_leak(caplog, exc_info)
