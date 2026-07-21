# Roadmap

Progress tracker for [plan.md](plan.md). One section per feature, in the order of plan.md §17.
Rules: check completed bullets in the same commit that completes their implementation; every
feature lists the test cases that cover it; never defer the roadmap update to a follow-up PR.

Feature PRs target the `integration` branch (see CLAUDE.md "Integration → main"). Because they
overlap heavily, sections 3, 6, and 7 (+ the package rename and tool pre-registration) are
implemented together on one branch: `feature/architecture-skeleton`.

Status legend: `[ ]` open · `[x]` done

## Wave status (snapshot 2026-07-20)

Per-section bullets are checked in the feature's completing commit. The table distinguishes
committed, PR, and merged state where that difference matters. All Phase 1 feature branches and
the integration refactor sweep are complete.

| Feature | Section | Branch | State |
|---|---|---|---|
| Architecture skeleton | 0/2/3/6/7 | — | ✅ **Merged** to `integration` (PR #2, `14fdbbc`) |
| Upstream reliability fixes | 2 | — | ✅ **Merged** to `integration` (PR #3, `3b30d3b`) |
| Structured logging + doctor | 4 | — | ✅ **Merged** to `integration` (PR #4, `3537363`) |
| Notebook registry | 5 | — | ✅ **Merged** to `integration` (PR #5, `e0d0657`) |
| Persistent auth | 9 | — | ✅ **Merged** to `integration` (PR #6, `b6468db`) |
| Snapshots | 8 | — | ✅ **Merged** to `integration` (PR #7, `da81a35`) |
| Direct file upload | 10 | — | ✅ **Merged** to `integration` (PR #8, `129ac72`) |
| Runtime control | 11 | — | ✅ **Merged** to `integration` (PR #9, `b809019`) |
| Integration refactor | — | `integration` | ✅ Combined `main...integration` sweep complete |
| Three-notebook live demo | manual verification | — | 🟡 OAuth, tab opening, CPU execution, and uploads verified; T4 verification remains |
| Local repository notebook sync | 5a | — | ✅ **Merged** to `integration` (PR #12, `0d6b419`) |
| Live Colab compatibility + output sync | 1/2/8/11 | — | ✅ **Merged** to `integration` (PR #14, `c95bdf3`) |
| CLI auto-approve wiring (managed browser in the MCP server) | 12 | — | ✅ **Merged** to `integration` (PR #18, `384e9fe`) and to `main` (PR #19) |
| README manual setup steps | 1 | — | ✅ **Merged** to `integration` (PR #20, `0012b34`) |
| GPU runtime-type binding + 1–2 notebook demo configs | 12/demo | — | ✅ **Merged** directly to `main` (PR #21, `4d5d25e`); reconciled into `integration` here |

Integration PRs #15 and #19 are merged. PR #21 (runtime-type UI binding for GPU notebooks,
`config.2nb.json`/`config.t4.json`, demo hardening from the remote Linux server) went to `main`
directly, against the feature workflow, and carried no roadmap update; this merge commit
reconciles it into `integration` and records it here. A 2026-07-20 run on a remote Linux
desktop (xrdp) completed a two-notebook end-to-end demo (auto-approve via `--cdp-url` attach,
execution, local sync); its T4 request was served a CPU runtime at the time. Whether the new
runtime-type binding yields a verified real T4 end-to-end run is still unconfirmed, so section
1's end-to-end bullet stays open.

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
- [x] Verify the real `add_code_cell` response shape (`{"newCellId": "..."}`) and tighten
      `run_code`'s cell-id parsing (`CELL_ID_KEYS` in constants.py) to that single key
- [x] Document the manual setup steps in README.md: install → MCP-client registration →
      one-time authentication (browser session via operator-launched Chrome + CDP attach;
      runtime-API OAuth consent) → unattended/headless operation via exported session file
      → remote Linux desktop caveats (xrdp `--disable-gpu`, SSH session env, keyring loss)
      → maintenance (`doctor`, `--list-running`, `--kill-stale`)

**Tests:** existing `session_test.py`, `websocket_server_test.py` pass. The live-demo harness is
covered offline by `demo/three_notebooks/demo_test.py`
(`test_plan_has_two_cpu_one_t4_and_isolated_upload_destinations`,
`test_relative_paths_resolve_from_the_demo_config`,
`test_plan_requires_three_unique_notebooks`, `test_plan_requires_two_cpu_and_one_t4`,
`test_plan_rejects_placeholder_local_path`,
`test_register_and_open_routes_three_notebooks_concurrently`,
`test_configure_requires_every_assignment_endpoint`,
`test_configure_routes_explicit_endpoints_and_profiles`,
`test_verify_upload_accepts_two_cpu_and_one_t4`,
`test_verify_upload_rejects_wrong_hardware` (CPU and T4 mismatch cases),
`test_verify_upload_rejects_unverified_upload`,
`test_structured_tool_failure_stops_demo_safely`); live response parsing is covered by
`session_test.py::TestRunCode::test_verified_cell_id_parsed_from_structured_or_text`

## 2. Upstream reliability fixes (plan.md Phase 1 Baseline)

Port from [SebastianGilPinzon/colab-mcp](https://github.com/SebastianGilPinzon/colab-mcp)
(Apache 2.0, cherry-pick with attribution):

- [x] Pre-register all notebook tools at startup (clients ignore `tools/list_changed`) — landed with the architecture skeleton (`feature/architecture-skeleton`)
- [x] IPv4/IPv6 dual-stack bind + Private Network Access CORS headers — adapted from the
      reference fork's IPv4-only bind to a true dual-stack bind (both families on one
      probed port). Note: the `websockets` library rejects non-GET methods before
      `process_request`, so a literal OPTIONS preflight cannot be answered; the decisive
      PNA headers ride on the upgrade response (and any parseable non-upgrade request
      gets a 204 with them)
- [x] Unique `?p=<port>` notebook URL to prevent stale Chrome tab reuse
- [x] Corrected Colab API signatures (`run_code_cell`/`cellId`, `move_cell`) — verified
      against the reference fork, the skeleton's schemas already match; `ColabClient`
      init lands with the runtime API (§11, no such client exists here yet). Live demo
      verification additionally confirmed `add_code_cell.language` and `cellIndex` are
      required. Public tools default to the reference indices (code `0`, text `-1`),
      shared execution uses code index `0`, and restore paths send each document index;
      every code path supplies the default `python` language.
- [x] Stale-server process registry with detection and cleanup (`--list-running`,
      `--kill-stale`, prune on startup; one entry per WebSocket server via `storage.py`)
- [x] Structured `not_connected` on mid-call WebSocket drop (today an unstructured
      exception surfaces)

**Tests:** (pre-registration) `server_test.py::TestStaticToolSurface`:
`test_all_tools_listed_while_disconnected`,
`test_notebook_tool_disconnected_returns_not_connected` (parametrized over every notebook
tool), `test_connected_tool_forwards_to_proxy_client` (parametrized);
(dual-stack + PNA) `websocket_server_test.py`:
`test_all_bound_sockets_share_the_reported_port`,
`test_connects_over_both_address_families` (parametrized IPv4/IPv6),
`test_non_upgrade_request_carries_private_network_access_headers`,
`test_upgrade_response_carries_private_network_access_headers`;
(tab dedup) `server_test.py::TestOpenColabBrowserConnection`:
`test_url_carries_port_param_before_the_fragment`,
`test_port_param_appends_to_an_existing_query`;
(process registry) `websocket_server_test.py::test_registers_on_start_and_unregisters_on_clean_stop`,
`process_registry_test.py` (`TestRegister`: `test_records_current_process`,
`test_prunes_dead_entries_on_the_way`, `test_one_entry_per_port_of_the_same_process`,
`test_concurrent_registrations_do_not_overwrite_each_other`;
`TestUnregister`: `test_removes_only_the_named_port`, `test_unknown_port_is_a_no_op`,
`test_concurrent_unregistrations_do_not_restore_entries`;
`TestPruneDead`: `test_removes_dead_keeps_alive`, `test_nothing_to_prune`;
`TestListRunning`: `test_filters_dead_pids`, `test_empty_registry`;
`TestKillStale`: `test_kills_foreign_and_drops_dead_but_never_self`,
`test_unkillable_entry_is_kept`; `TestCorruptRegistry`: `test_invalid_json_is_ignored`,
`test_wrong_shape_is_ignored`; `TestTerminate`: `test_sigterm_suffices`,
`test_escalates_to_sigkill`, `test_gives_up_on_immortal_process`), and
`cli_test.py` (`TestParseArgs`: `test_flags_default_off`, `test_flags_recognized`;
`TestListRunning`: `test_prints_entries_and_exits_before_serving`,
`test_empty_registry_prints_notice`; `TestKillStale`: `test_kills_and_reports_then_exits`,
`test_nothing_stale_prints_notice`; `TestNormalStartup`:
`test_prunes_dead_entries_then_serves`);
(mid-call drop) `session_test.py::TestNotebookSessionCallTool`:
`test_mid_call_drop_raises_structured_not_connected`,
`test_error_while_still_connected_propagates`, `test_mid_call_drop_during_run_code`

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

- [x] Structured logging across server, sessions, and WebSocket layers: namespaced
      `cool_colab_mcp.<module>` loggers, one timestamp/level/name/message format
      (`logging_setup.py`), file logging under `--log`, `-v/--verbose` for DEBUG;
      tokens and token-carrying URLs are never logged (port, notebook_id, and event only)
- [x] `doctor` subcommand (`cool-colab-mcp doctor`) that checks config and connectivity:
      Python/package versions, storage dir (`COOL_COLAB_MCP_HOME`) writable, log dir
      writable, WebSocket port bind, stale-server registry, `COLAB_MCP_NOTEBOOK_URL` pin
      (informational); pass/fail per check with a fix hint, exit 0/1
- [ ] Auth-state doctor checks arrive with persistent auth (section 9) by appending to
      `doctor.run_checks`

**Tests:** `doctor_test.py` (`TestChecks::test_all_checks_pass_in_healthy_env`,
`TestChecks::test_python_version_too_old_fails`,
`TestChecks::test_package_metadata_missing_fails`,
`TestChecks::test_storage_dir_blocked_by_file_fails`,
`TestChecks::test_log_dir_blocked_by_file_fails`,
`TestChecks::test_port_bind_failure_fails`,
`TestChecks::test_env_pin_is_informational_either_way`,
`TestChecks::test_no_stale_servers_passes`,
`TestChecks::test_registered_servers_fail_with_cleanup_hint`,
`TestChecks::test_registry_read_failure_is_actionable`,
`TestMain::test_exit_zero_and_pass_lines_when_healthy`,
`TestMain::test_exit_one_and_fail_line_on_failure`,
`TestMain::test_cli_doctor_subcommand_exits_with_check_status`,
`TestParseArgs::test_doctor_subcommand_parsed`, `TestParseArgs::test_default_is_serve`),
`logging_setup_test.py`
(`TestInitLogging::test_record_format_has_timestamp_level_name_message`,
`TestInitLogging::test_logs_its_own_destination`,
`TestInitLogging::test_default_level_is_info`,
`TestInitLogging::test_verbose_enables_debug`,
`TestInitLogging::test_verbose_flag_parses_and_sets_debug`,
`TestInitLogging::test_missing_log_dir_raises`,
`TestNamespacedLoggers::test_module_logger_is_namespaced_after_its_module` (parametrized
over every instrumented module), `TestNamespacedLoggers::test_registry_failure_uses_websocket_module_logger`,
`TestNoSecretsInLogs::test_session_token_never_logged_when_opening_connection`)

## 5. Notebook registry (plan.md §4)

- [x] Persistent notebook records (id, name, url, preferred_runtime) — `registry/records.py`
      on top of `storage.py`; `preferred_runtime` is stored only, behavior arrives with §8
- [x] Tools: `register_notebook`, `list_notebooks`, `remove_notebook`, `get_notebook_status`
      (`registry/tools.py`, wired into `build_server`)
- [x] `open_notebook` / `close_notebook` resolve a registered id and open via notebook
      targeting — `open_notebook` reuses the exact `open_colab_browser_connection` flow
      (extracted as `server.open_connection`) with the registered URL as `notebook_url`
      and the registry id as the session `notebook_id`
- [x] Registry survives server restart

**Tests:** `records_test.py::TestNotebookRecord`
(`test_empty_or_reserved_notebook_id_rejected` (parametrized),
`test_url_validated_with_validate_notebook_url`, `test_preferred_runtime_optional_and_stored`),
`records_test.py::TestNotebookRegistry` (`test_corrupted_store_raises_structured_error`,
`test_register_get_roundtrip`, `test_list_all_records`,
`test_concurrent_registrations_do_not_overwrite_records`,
`test_reregister_same_id_updates`, `test_remove`, `test_get_unknown_raises_structured_error`,
`test_concurrent_removals_do_not_restore_records`,
`test_remove_unknown_raises_structured_error`, `test_persists_across_reinstantiation`),
`registry_tools_test.py::TestToolSurface::test_registry_tools_listed`,
`registry_tools_test.py::TestRegisterNotebook` (`test_registers_and_returns_record`,
`test_reregistering_existing_id_updates`, `test_invalid_url_returns_invalid_input`,
`test_empty_notebook_id_returns_invalid_input`),
`registry_tools_test.py::TestListNotebooks` (`test_empty_registry_lists_nothing`,
`test_lists_all_records`), `registry_tools_test.py::TestRemoveNotebook`
(`test_removes_record`, `test_unknown_id_returns_unknown_notebook`),
`registry_tools_test.py::TestGetNotebookStatus` (`test_unknown_id_returns_unknown_notebook`,
`test_registered_without_session`, `test_disconnected_session`,
`test_connected_session_reports_active_url`), `registry_tools_test.py::TestOpenNotebook`
(`test_opens_registered_url_and_names_session`, `test_unknown_id_returns_unknown_notebook`,
`test_already_connected_returns_without_reopening`,
`test_session_connected_to_other_notebook_returns_invalid_input`,
`test_reports_progress_while_waiting`), `registry_tools_test.py::TestCloseNotebook`
(`test_closes_session_but_keeps_record`,
`test_registered_but_never_opened_closes_idempotently`,
`test_unregistered_id_returns_unknown_notebook`),
`registry_tools_test.py::TestPersistenceAcrossRestart::test_registry_survives_server_restart`

## 5a. Local repository notebook synchronization (plan.md §4)

- [x] Registry records accept exactly one source: a Colab URL or an allowed local `.ipynb`
- [x] Opening a local record restores its cells into an independent Colab scratch session
- [x] Explicit local → Colab reload and atomic Colab → local sync tools
- [x] Host notebook access restricted by `COOL_COLAB_MCP_NOTEBOOK_DIRS`
- [x] Three-notebook demo uses tracked repository notebooks and syncs them back after verification

**Tests:** `records_test.py::TestNotebookRecord`
(`test_exactly_one_remote_or_local_source_is_required`,
`test_local_notebook_source_is_stored`),
`records_test.py::TestNotebookRegistry`
(`test_local_record_remains_removable_after_file_disappears`),
`registry_tools_test.py::TestRegisterNotebook`
(`test_registers_allowed_local_notebook`,
`test_local_notebook_outside_allowlist_is_rejected`),
`registry_tools_test.py::TestLocalNotebookSync`
(`test_open_local_notebook_restores_it_into_scratch_colab`,
`test_sync_to_colab_replaces_cells`,
`test_sync_to_local_atomically_writes_current_cells`,
`test_remote_record_rejects_local_sync` (both directions),
`test_unknown_notebook_is_structured` (both directions),
`test_disconnected_local_notebook_is_structured` (both directions),
`test_malformed_local_file_fails_without_touching_colab`,
`test_failed_sync_to_local_preserves_original_file`), and `demo_test.py`
(`test_plan_rejects_placeholder_local_path`,
`test_register_and_open_routes_three_notebooks_concurrently`,
`test_verify_upload_accepts_two_cpu_one_t4`).

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

- [x] Tools: `create_snapshot`, `list_snapshots`, `restore_snapshot`, `export_notebook`
- [x] Snapshots are valid `.ipynb` files
- [x] Snapshots survive server restart
- [x] Outputs returned by live `run_code_cell` calls are cached per session and merged
      into snapshots/exports when Colab's later `get_cells` payload omits them

**Tests:** `snapshot_manager_test.py`
(`test_notebook_document_preserves_cells_metadata_and_outputs`,
`test_notebook_document_stores_recovery_metadata`,
`test_unexpected_cell_payload_is_protocol_error`,
`test_malformed_frontend_cells_are_rejected` (parametrized),
`test_create_list_load_roundtrip_survives_reinstantiation`,
`test_unknown_snapshot_is_structured_invalid_input`,
`test_snapshot_id_cannot_escape_notebook_directory`,
`test_notebook_id_cannot_escape_snapshot_directory`,
`test_corrupt_snapshot_is_protocol_error`,
`test_schema_invalid_snapshot_is_protocol_error`,
`test_create_filesystem_failure_is_structured`,
`test_list_filesystem_failure_is_structured`, `test_export_requires_ipynb_suffix`,
`test_export_writes_valid_notebook`) and `snapshots_tools_test.py`
(`test_create_snapshot_writes_valid_ipynb`,
`test_create_snapshot_merges_cached_outputs_when_frontend_omits_them`,
`test_create_snapshot_stores_recovery_metadata`,
`test_create_snapshot_disconnected_is_structured`,
`test_create_snapshot_unknown_notebook_is_structured`,
`test_list_snapshots_survives_server_restart`,
`test_list_snapshots_rejects_empty_notebook_id`,
`test_list_snapshots_filesystem_failure_is_structured`,
`test_restore_snapshot_replaces_cells_in_order`,
`test_restore_unknown_snapshot_is_structured`,
`test_restore_disconnected_is_structured`,
`test_restore_unknown_notebook_is_structured`,
`test_export_notebook_writes_current_cells`,
`test_export_merges_outputs_returned_by_run_cell`,
`test_export_keeps_fresh_frontend_outputs_over_cached_outputs`,
`test_export_bad_destination_is_structured`,
`test_export_disconnected_is_structured`,
`test_export_unknown_notebook_is_structured`,
`test_export_filesystem_failure_is_structured`) and `session_test.py`
(`TestResolveNotebookUrl::test_explicit_url_replaces_previous_active`,
`TestResolveNotebookUrl::test_reconnect_same_url_keeps_cached_outputs`,
`TestResolveNotebookUrl::test_fallback_to_explicit_url_clears_cached_outputs`,
`TestRunCode::test_happy_path`,
`TestRunCode::test_public_run_code_cell_caches_outputs_for_persistence`,
`TestRunCode::test_cached_code_outputs_never_merge_into_markdown`)

## 9. Persistent authentication (plan.md §3)

- [ ] Persistent Chromium profile for the Google/Colab session — groundwork only:
      profile-directory constant (`BROWSER_PROFILE_DIR_NAME` under the base dir) and
      gitignore entry landed here; actual Chromium profile management is Phase 2 (§12)
- [x] Credentials in OS keyring / encrypted storage, never exposed to agents (`auth/manager.py`)
- [x] Runtime-API OAuth token in keyring (hardened vs. reference fork's plaintext JSON);
      `ensure_credentials` + `run_consent_flow` in `auth/oauth.py` — scopes and the
      port-8085 consent callback ported from SebastianGilPinzon/colab-mcp (Apache 2.0)
- [x] Expired auth → structured `user_action_required` (missing config, missing token,
      failed refresh/transport, no refresh token, unavailable keyring, malformed config,
      declined consent — all with actionable messages)

**Tests:** `auth_manager_test.py` (keyring store; named `auth_manager_test.py` because
`manager_test.py` is taken by the session manager):
`test_roundtrip_preserves_token_and_refresh_token`,
`test_token_lives_under_the_configured_service_and_account`,
`test_load_without_stored_token_returns_none`, `test_load_with_corrupt_entry_returns_none`,
`test_load_with_incomplete_entry_returns_none`, `test_delete_removes_the_token`,
`test_delete_without_stored_token_is_a_noop`,
`test_missing_keyring_backend_requires_user_action` (parametrized over store/load/delete);
`oauth_test.py::TestEnsureCredentials`
(`test_valid_cached_token_is_returned`, `test_expired_token_is_refreshed_and_persisted`,
`test_missing_token_requires_consent`, `test_missing_token_and_config_names_the_config_path`,
`test_failed_refresh_requires_consent_and_clears_the_token`,
`test_expired_token_without_refresh_token_requires_consent`),
`oauth_test.py::TestRunConsentFlow` (`test_consent_stores_the_token`,
`test_consent_uses_the_reference_fork_port`, `test_missing_config_requires_user_action`,
`test_malformed_config_requires_user_action`,
`test_declined_consent_requires_user_action_and_stores_nothing`),
`oauth_test.py::TestNoTokenLeakage` (`test_happy_path_logs_no_token`,
`test_leaky_refresh_error_is_not_propagated`,
`test_leaky_transport_error_is_not_propagated`,
`test_leaky_consent_error_is_not_propagated`
— a sentinel token value must never appear in log records, error messages, details, or
exception chains)

## 10. Direct file upload (plan.md §7)

- [x] Chunked transfer via notebook code execution, reassembled under `/content`
- [x] SHA-256 + size verification; cleanup of incomplete uploads
- [x] Tools: `upload_file`, `upload_directory`, `get_upload_status`, `cancel_upload`, `list_runtime_files`
- [x] Host file access restricted to configured directories

**Tests:** `transfers_test.py` (`TestUploadFile::test_chunks_and_verifies_file`,
`test_verification_failure_cleans_incomplete_file`,
`test_transfer_failure_cleans_incomplete_file`, `test_cleanup_failure_is_reported_honestly`,
`test_cancelled_upload_is_cleaned`, `test_duplicate_caller_supplied_upload_id_rejected`,
`test_empty_caller_supplied_upload_id_rejected`,
`test_concurrent_destination_collision_is_rejected`;
`TestPathRestrictions::test_uploads_disabled_without_configuration`,
`test_source_outside_allowed_root_rejected`, `test_destination_outside_content_rejected`;
`TestUploadDirectory::test_recurses_and_preserves_relative_paths`;
`TestRuntimeFiles::test_lists_runtime_files`, `test_invalid_runtime_response_is_structured`,
`test_runtime_resolved_path_escape_is_invalid_input` (parametrized over upload/remove/list),
`test_runtime_code_resolves_paths_beneath_content`;
`TestStatus::test_unknown_upload_id_rejected`), `transfer_tools_test.py`
(`TestToolSurface::test_transfer_tools_are_pre_registered`,
`test_session_tools_return_not_connected` (parametrized);
`TestUploadFileTool::test_uploads_and_returns_status`,
`test_bad_host_path_returns_structured_error`, `test_failure_is_structured`,
`test_routes_to_named_notebook`; `TestUploadDirectoryTool::test_happy_path`,
`test_file_source_is_invalid`, `test_child_failure_is_structured_and_routes`;
`TestStatusAndCancelTools::test_active_status_and_cancel_happy_path`,
`test_unknown_id_is_invalid` (parametrized); `TestListRuntimeFilesTool::test_happy_path_routes_to_named_notebook`,
`test_path_outside_content_is_invalid`, `test_bad_runtime_response_is_structured`)

## 11. Runtime status, profiles, and API-based switching (plan.md §8)

- [x] Tools: `get_runtime_status`, `connect_runtime`, `disconnect_runtime`, `stop_runtime`, `restart_runtime`, `request_runtime_profile`
- [x] CPU/GPU switching via the OAuth-authenticated Colab runtime API, including
      quota/denial outcomes as structured results
- [x] Live verification corrected `/tun/m` assignment routing to
      `colab.research.google.com` with `authuser=0` (the `colab.pa.googleapis.com`
      origin returns HTML 404 for these routes)
- [ ] Pre-stop save/snapshot/manifest sequence; post-connect verify/restore sequence

Phase-1 boundary: destructive tools require caller-confirmed external notebook/snapshot/log/
checkpoint preservation, generate the environment manifest through `NotebookSession.run_code`,
and release only an explicitly selected assignment endpoint. `connect_runtime` verifies actual
hardware. Automatic save/snapshot/bootstrap/checkpoint orchestration remains Phase 2 (§14).

Runtime-control coverage in `runtime_client_test.py`
(`test_list_assignments_strips_xssi`, `test_quota_denial_is_structured`,
`test_future_quota_denial_is_structured`, `test_auth_denial_is_actionable_without_body_leak`,
`test_403_recognized_policy_outcome_is_preserved`,
`test_invalid_assignment_is_protocol_error`,
`test_transport_error_does_not_leak_credentials`, `test_unassign_uses_server_token`,
`test_empty_unassign_endpoint_is_invalid_input`) and
`runtime_tools_test.py` (`test_status_without_session_returns_structured_error`,
`test_status_uses_shared_run_code`, `test_connect_runtime_verifies_hardware`,
`test_status_backend_failure_is_structured`, `test_every_runtime_tool_rejects_bad_notebook`,
`test_profile_preserves_then_switches`, `test_profile_sequence_is_manifest_release_assign`,
`test_unknown_profile_is_invalid_input`, `test_switch_without_oauth_is_actionable`,
`test_switch_requires_preservation_confirmation`,
`test_stop_without_mapping_releases_nothing`, `test_stop_releases_only_selected_assignment`,
`test_restart_rejects_unknown_accelerator`, `test_restart_switches_only_selected_assignment`,
`test_api_backend_failure_is_structured`, `test_disconnect_closes_only_local_session`,
`test_disconnect_backend_failure_is_structured`). Full automatic
snapshot/bootstrap/checkpoint orchestration remains Phase 2 (§14).

---

# Phase 2 (plan.md §10–15)

## 12. Playwright browser management

- [x] `BrowserController`: managed Chromium, persistent profile, one page per `notebook_id`
- [x] Grant Chrome's `local-network-access` permission, scoped to the Colab origin
- [x] Replace `webbrowser.open_new` in `server.open_connection` (wiring + opt-in flag):
      `--auto-approve` (+ `--cdp-url` / `--headless` / `--session-file`) on the CLI builds
      a `BrowserController`, starts it, passes it as `SessionManager(browser=...)`, and
      closes it on shutdown; behaviour is byte-identical when the flags are absent, and
      the dependent flags without `--auto-approve` are rejected as bad input
- [ ] Tab recovery after a browser crash; login/consent page detection
- [ ] Xvfb / headless deployment (see section 15)

**Tests:** `approval_test.py` (see section 13);
`browser_wiring_test.py::TestManagedBrowserWiring` (server side);
`cli_test.py::TestAutoApprove`
(`test_flags_default_off_and_recognized`,
`test_invalid_flag_combinations_are_rejected` (parametrized: dependent flags
without `--auto-approve`; `--cdp-url` with `--headless`/`--session-file`),
`test_wires_browser_into_manager_and_closes_it_on_shutdown`,
`test_session_file_reaches_the_controller_as_a_path`,
`test_without_flag_no_browser_is_built`,
`test_start_failure_aborts_before_serving_and_releases_browser`,
`test_browser_closes_even_when_manager_close_fails`,
`test_actionable_start_failure_exits_cleanly_without_traceback`).

## 13. Automated MCP popup approval

Mechanism established empirically 2026-07-16 (frontend-bundle analysis + headless
end-to-end spike against the real Colab UI and a real `ColabWebSocketServer`); the full
findings, DOM surface, and failure modes are in plan.md §11 "Verified mechanism".

- [x] **Confirmed the popup cannot be bypassed**: Colab's `connect-local-mcp` command
      always awaits the dialog, there is no "remember" option, and the only dialog-free
      path is a private `TEST_ONLY.connect()` hook we refuse to use (plan.md §14)
- [x] Detect the dialog (`mwc-dialog.local-mcp-connect-dialog`, `state="attached"` — the
      host has no layout box)
- [x] Verify before clicking: Colab origin + the dialog's readonly `<token>&<port>` field
      matches this session; refuse otherwise, without leaking the token
- [x] Click Connect; success is the **server-side** connection signal, not the click
- [x] Structured `user_action_required` when the dialog never appears (UI changed or the
      `enable_colab_mcp_integration` flag is off)
- [ ] Bounded-backoff retry around the approval attempt
- [ ] Reconnect-after-drop path (re-navigate + re-approve)

**Tests:** `approval_test.py::TestApprove` (`test_clicks_connect_when_dialog_is_ours`,
`test_missing_dialog_is_user_action_required`, `test_refuses_unexpected_origin`,
`test_refuses_when_dialog_shows_another_sessions_token`,
`test_refuses_when_dialog_shows_another_port`, `test_refusal_never_leaks_the_token`)

## 14. Automated runtime-switch orchestration (snapshot → switch → verify → restore)
## 15. Headless deployment and recovery

*(broken into bullets when Phase 1 is complete)*
