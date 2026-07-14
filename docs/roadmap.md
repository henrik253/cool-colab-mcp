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
- [ ] Rename package `colab_mcp` → `cool_colab_mcp` (plan.md §16)

**Tests:** none (infrastructure only; CI proves itself on the first PR)

## 1. Reproduce upstream workflow

- [ ] Fork runs locally end-to-end against a real Colab notebook (manual verification)
- [ ] Document the manual setup steps in README.md

**Tests:** existing `session_test.py`, `websocket_server_test.py` pass

## 2. Upstream reliability fixes (plan.md Phase 1 Baseline)

Port from [SebastianGilPinzon/colab-mcp](https://github.com/SebastianGilPinzon/colab-mcp)
(Apache 2.0, cherry-pick with attribution):

- [ ] Pre-register all notebook tools at startup (clients ignore `tools/list_changed`)
- [ ] IPv4/IPv6 dual-stack bind + Private Network Access CORS headers
- [ ] Unique `?p=<port>` notebook URL to prevent stale Chrome tab reuse
- [ ] Corrected Colab API signatures (`run_code_cell`/`cellId`, `move_cell`, `ColabClient` init)
- [ ] Stale-server process registry with detection and cleanup

**Tests:** —

## 3. Per-connection notebook targeting (plan.md "Per-Connection Notebook Targeting")

- [ ] Optional `notebook_url` parameter on `open_colab_browser_connection`; passed URL becomes the session's active notebook
- [ ] Fallback order without parameter: active notebook → `COLAB_MCP_NOTEBOOK_URL` env → scratch
- [ ] Reconnect after a WebSocket drop reopens the active notebook, not scratch
- [ ] Both URL forms accepted: GitHub-backed (`/github/...`) and Drive (`/drive/<FILE_ID>`)
- [ ] Switching notebooks needs no config edit or server restart
- [ ] Tool description documents the GitHub-URL caveat (content loads from the remote branch)

**Tests:** —

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

- [ ] Extract session state (page, WebSocket server, token/port, proxy client, lock, active notebook) into one class

**Tests:** —

## 7. Multi-notebook routing (plan.md §6)

- [ ] One WebSocket server instance per notebook
- [ ] All notebook tools take `notebook_id` and route to the right session
- [ ] Writes within one notebook serialized; operations across notebooks concurrent

**Tests:** —

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
