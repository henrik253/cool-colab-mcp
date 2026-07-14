# Roadmap

Progress tracker for [plan.md](plan.md). One section per feature, in the order of plan.md §17.
Rules: check bullets as they land; every feature lists the test cases that cover it; update this
file in the same branch as the feature itself.

Feature PRs target the `integration` branch (see CLAUDE.md "Integration → main"). Because they
overlap heavily, sections 3, 6, and 7 (+ the package rename and tool pre-registration) are
implemented together on one branch: `feature/architecture-skeleton`.

Status legend: `[ ]` open · `[x]` done

---

## 0. Project bootstrap

- [x] Copy plan.md into the repo
- [x] CLAUDE.md with workflow, style, and security rules
- [x] roadmap.md (this file)
- [x] `plan-reviewer` agent definition
- [x] GitHub Actions CI (ruff + pytest on every PR)
- [x] Pre-commit trimmed to ruff (pytest moved to CI)
- [x] All markdown docs moved to `docs/` (README.md and CLAUDE.md stay at root)
- [x] Constants extracted to `constants.py` (no inline URLs/paths/magic values)
- [x] README rewritten: goal → features → architecture
- [x] Rename package `colab_mcp` → `cool_colab_mcp` (plan.md §16)

**Tests:** the whole suite runs against the renamed `cool_colab_mcp` package. The state
store (`storage.py`) lands here deliberately even though its first callers come later:
sections 2 (process registry), 5 (notebook registry), and 9 (auth) are developed on
parallel branches and must share one persistence implementation. Covered by
`errors_test.py` (structured-error contract: `test_as_result_carries_error_as_text_and_structured_content`,
`test_details_included_when_present`, `test_fail_builds_a_raisable_tool_failed`,
`test_unknown_kind_rejected`) and `storage_test.py` (atomic JSON store: `test_roundtrip`,
`test_missing_store_loads_empty`, `test_save_creates_base_dir`, `test_home_env_override`,
`test_default_base_dir_without_env`, `test_failed_save_leaves_no_partial_file`)

## 1. Reproduce upstream workflow

- [ ] Fork runs locally end-to-end against a real Colab notebook (manual verification)
- [ ] Verify the real `add_code_cell` response shape and tighten `run_code`'s cell-id
      parsing (`CELL_ID_KEYS` in constants.py) to the single verified key
- [ ] Document the manual setup steps in README.md

**Tests:** existing `session_test.py`, `websocket_server_test.py` pass

## 2. Upstream reliability fixes (plan.md Phase 1 Baseline)

Port from [SebastianGilPinzon/colab-mcp](https://github.com/SebastianGilPinzon/colab-mcp)
(Apache 2.0, cherry-pick with attribution):

- [x] Pre-register all notebook tools at startup (clients ignore `tools/list_changed`) — landed with the architecture skeleton (`feature/architecture-skeleton`)
- [ ] IPv4/IPv6 dual-stack bind + Private Network Access CORS headers
- [ ] Unique `?p=<port>` notebook URL to prevent stale Chrome tab reuse
- [ ] Corrected Colab API signatures (`run_code_cell`/`cellId`, `move_cell`, `ColabClient` init)
- [ ] Stale-server process registry with detection and cleanup
- [ ] Structured `not_connected` on mid-call WebSocket drop (today an unstructured
      exception surfaces)

**Tests:** (pre-registration) `server_test.py::TestStaticToolSurface`:
`test_all_tools_listed_while_disconnected`,
`test_notebook_tool_disconnected_returns_not_connected` (parametrized over every notebook
tool), `test_connected_tool_forwards_to_proxy_client` (parametrized); the remaining
bullets get their tests with their fixes

## 3. Per-connection notebook targeting (plan.md "Per-Connection Notebook Targeting")

- [x] Optional `notebook_url` parameter on `open_colab_browser_connection`; passed URL becomes the session's active notebook
- [x] Fallback order without parameter: active notebook → `COLAB_MCP_NOTEBOOK_URL` env → scratch
- [x] Reconnect after a WebSocket drop reopens the active notebook, not scratch
- [x] Both URL forms accepted: GitHub-backed (`/github/...`) and Drive (`/drive/<FILE_ID>`); other hosts/paths → structured `invalid_input`
- [x] Switching notebooks needs no config edit or server restart
- [x] Tool description documents the GitHub-URL caveat (content loads from the remote branch)

**Tests:** `session_test.py::TestValidateNotebookUrl` (`test_accepted_forms`,
`test_rejected_forms`), `session_test.py::TestResolveNotebookUrl`
(`test_explicit_url_wins_and_becomes_active`, `test_explicit_url_replaces_previous_active`,
`test_active_notebook_reused_without_parameter`, `test_env_pin_fallback`,
`test_scratch_fallback`, `test_invalid_url_rejected_and_active_unchanged`),
`server_test.py::TestOpenColabBrowserConnection`
(`test_explicit_url_opens_tab_and_becomes_active`,
`test_github_url_accepted_with_caveat_documented`,
`test_invalid_url_returns_invalid_input_and_creates_no_session`,
`test_reconnect_without_parameter_returns_to_active`, `test_env_pin_fallback`,
`test_scratch_fallback`, `test_already_connected_returns_without_reopening`,
`test_notebook_id_creates_an_independent_session`, `test_reports_progress_while_waiting`)

## 4. Structured logging and `doctor`

- [ ] Structured logging across server, sessions, and WebSocket layers
- [ ] `doctor` command that checks config, auth state, connectivity, and stale servers

**Tests:** —

## 5. Notebook registry (plan.md §4)

- [ ] Persistent notebook records (id, name, url, preferred_runtime)
- [ ] Tools: `register_notebook`, `list_notebooks`, `remove_notebook`, `get_notebook_status`
- [ ] `open_notebook` / `close_notebook` resolve a registered id and open via notebook targeting
- [ ] Registry survives server restart

**Tests:** —

## 6. Reusable `NotebookSession` (plan.md §6)

- [x] Extract session state (WebSocket server, token/port, proxy client, lock, active notebook) into one class — the browser-page handle arrives with Phase 2 §10 (nothing to hold via `webbrowser.open_new`)
- [x] `run_code(code)` shared execution channel (add cell + run it), mockable at the proxy-client boundary

**Tests:** `session_test.py::TestNotebookSessionLifecycle`
(`test_start_owns_wss_and_proxy_client`, `test_token_and_port_delegate_to_wss`,
`test_await_connection_without_start_is_false`),
`session_test.py::TestNotebookSessionCallTool`
(`test_disconnected_raises_structured_error`, `test_forwards_and_strips_none_args`,
`test_serializes_via_session_lock`), `session_test.py::TestRunCode` (`test_happy_path`,
`test_cell_id_parsed_from_wrapper_or_text`, `test_unstructured_run_result_returned_as_text`,
`test_missing_cell_id_fails`, `test_proxy_failure_propagates`,
`test_disconnected_raises_structured_error`), `session_test.py::TestColabProxyClient`
(`test_is_connected`, `test_await_connection_success`,
`test_await_connection_timeout_keeps_start_task_alive`,
`test_await_connection_before_start_is_false`, `test_start_proxy_client`,
`test_call_tool_forwards_to_mcp_client`, `test_aexit_cancels_pending_start`),
`session_test.py::TestColabTransport::test_connect_session`

## 7. Multi-notebook routing (plan.md §6)

- [x] One WebSocket server instance per notebook
- [x] All notebook tools take `notebook_id` and route to the right session
- [x] Writes within one notebook serialized; operations across notebooks concurrent

**Tests:** `manager_test.py` (`TestGetOrCreate::test_without_id_creates_the_default_session`,
`TestGetOrCreate::test_same_id_returns_same_session`,
`TestGetOrCreate::test_sessions_have_own_server_token_and_port`,
`TestGet::test_unknown_id_raises_structured_error`,
`TestGet::test_without_id_before_any_open_raises_not_connected`,
`TestGet::test_returns_existing_session`,
`TestRouting::test_two_sessions_route_independently`,
`TestRouting::test_sessions_operate_concurrently`,
`TestClose::test_close_forgets_the_session`,
`TestClose::test_close_unknown_id_raises_structured_error`,
`TestClose::test_aclose_shuts_every_session`),
`server_test.py::TestStaticToolSurface`
(`test_unknown_notebook_id_returns_structured_error`,
`test_tool_routes_to_the_session_named_by_notebook_id`),
`session_test.py::TestNotebookSessionCallTool::test_serializes_via_session_lock`

## 8. Notebook snapshots (plan.md §5)

- [ ] Tools: `create_snapshot`, `list_snapshots`, `restore_snapshot`, `export_notebook`
- [ ] Snapshots are valid `.ipynb` files
- [ ] Snapshots survive server restart

**Tests:** —

## 9. Persistent authentication (plan.md §3)

- [ ] Persistent Chromium profile for the Google/Colab session
- [ ] Credentials in OS keyring / encrypted storage, never exposed to agents
- [ ] Runtime-API OAuth token in keyring (hardened vs. reference fork's plaintext JSON)
- [ ] Expired auth → structured `user_action_required`

**Tests:** —

## 10. Direct file upload (plan.md §7)

- [ ] Chunked transfer via notebook code execution, reassembled under `/content`
- [ ] SHA-256 + size verification; cleanup of incomplete uploads
- [ ] Tools: `upload_file`, `upload_directory`, `get_upload_status`, `cancel_upload`, `list_runtime_files`
- [ ] Host file access restricted to configured directories

**Tests:** —

## 11. Runtime status, profiles, and API-based switching (plan.md §8)

- [ ] Tools: `get_runtime_status`, `connect_runtime`, `disconnect_runtime`, `stop_runtime`, `restart_runtime`, `request_runtime_profile`
- [ ] CPU/GPU switching via the OAuth runtime API (`colab.pa.googleapis.com`), incl. quota/denial outcomes as structured results
- [ ] Pre-stop save/snapshot/manifest sequence; post-connect verify/restore sequence

**Tests:** —

---

# Phase 2 (plan.md §10–15)

## 12. Playwright browser management
## 13. Automated MCP popup approval
## 14. Automated runtime-switch orchestration (snapshot → switch → verify → restore)
## 15. Headless deployment and recovery

*(broken into bullets when Phase 1 is complete)*
