# Agent guide

Everything an AI agent needs to use Cool Colab MCP well, on one page. Read this once at
the start of a session; the tool descriptions repeat the details.

## Mental model

- **Registered notebooks are persistent resources.** Browser tabs, WebSocket connections,
  and Colab runtimes are replaceable sessions attached to them. Register once, reopen
  forever — the registry survives server restarts.
- **Every notebook tool takes `notebook_id`** and routes to that notebook's own session.
  Different notebooks operate concurrently; operations within one notebook are serialized
  for you. Omitting `notebook_id` does **not** mean "the last one used" — it targets the
  fixed session named `default`, the one opened by calls that themselves omitted the id.
  When you open notebooks by id, always pass the id.
- **Failures are structured, not exceptions.** Every error names a `kind` and a remedy.
  `user_action_required` means a human must do something (sign in, run consent, fix
  config) — report it to the user verbatim instead of retrying or working around it.

## Tool map

| Goal | Call |
|---|---|
| **Make a notebook durable** | `register_notebook(notebook_id, name, url=… \| local_path=…, preferred_runtime=…)` |
| See what exists / its state | `list_notebooks()`, `get_notebook_status(notebook_id)` |
| Open a registered notebook | `open_notebook(notebook_id)` |
| Close its session (record stays) | `close_notebook(notebook_id)` |
| Forget the record | `remove_notebook(notebook_id)` |
| **Edit and run cells** | `add_code_cell`, `add_text_cell`, `run_code_cell`, `update_cell`, `delete_cell`, `move_cell`, `get_cells` — all take `notebook_id` |
| One-off notebook by URL (no registry) | `open_colab_browser_connection(notebook_url=…)` |
| **Save results to the repo** | `sync_notebook_to_local(notebook_id)` — atomic write to the registered `.ipynb` |
| Reset Colab from the repo file | `sync_notebook_to_colab(notebook_id)` — discards the tab's cells |
| **Checkpoint before risk** | `create_snapshot(notebook_id)`; back with `restore_snapshot(snapshot_id, notebook_id)` — cells return, outputs stay only in the `.ipynb` (Colab cannot re-inject them); `list_snapshots(notebook_id)` |
| Export anywhere as `.ipynb` | `export_notebook(destination, notebook_id)` |
| **Get files into the runtime** | `upload_file(source, destination, notebook_id)`, `upload_directory(…)` — chunked, SHA-256-verified, into `/content` |
| Watch / cancel / browse uploads | `get_upload_status(upload_id)`, `cancel_upload(upload_id)`, `list_runtime_files(notebook_id)` |
| **Check the hardware** | `get_runtime_status(notebook_id)`, `connect_runtime(notebook_id)` — verifies what is actually attached |
| Switch CPU/GPU | `request_runtime_profile(profile, notebook_id, preservation_confirmed=True, assignment_endpoint=…)` |
| Stop / restart / detach | `stop_runtime(…)`, `restart_runtime(accelerator, …)`, `disconnect_runtime(notebook_id)` |

Runtime profiles: `prototype-cpu` (no accelerator), `debug-gpu` (T4), `training-gpu`
(L4). Raw accelerators: `NONE`, `T4`, `L4`, `A100`, plus TPU variants.

## Standard workflows

**Project setup (once per project)**
1. The user sets `COOL_COLAB_MCP_NOTEBOOK_DIRS` (and `COOL_COLAB_MCP_UPLOAD_DIRS` for
   data) to the project directory before starting the server — local paths outside these
   allowlists are refused.
2. `register_notebook` each project notebook with a stable, meaningful id
   (`preprocess`, `train`, `evaluate`, …) and a `preferred_runtime` per role. Prefer
   `local_path` for repo-tracked notebooks: results then sync back into git.

**Every work session**
1. `list_notebooks()` → `open_notebook(id)` for what you need now — not everything at
   once; each open notebook holds a browser tab and a Colab runtime, and Colab's quotas
   are the real ceiling.
2. Work with the cell tools; upload data with `upload_file` rather than re-downloading
   inside the notebook.
3. After every meaningful result: `sync_notebook_to_local(id)`. **`close_notebook` does
   not sync** — an accidental close cannot overwrite local work. The flip side: for
   `local_path` notebooks, reopening restores from the last-synced local file, so any
   Colab-side work since the last sync is **gone**. Sync early, sync often.

**Switching to a GPU (or any runtime change)**
1. `create_snapshot(notebook_id)` — runtime switches replace the VM; unsaved state dies.
2. Discover the endpoints: call `request_runtime_profile(profile, notebook_id,
   preservation_confirmed=True)` **without** `assignment_endpoint`. No runtime is
   released; the structured `user_action_required` reply lists the account's
   `assignment_endpoints`. The server cannot tell which endpoint belongs to which
   notebook — if more than one exists, ask the user rather than guessing (a wrong pick
   stops someone else's runtime).
3. Retry the same call with the chosen `assignment_endpoint=…`.
4. `connect_runtime(notebook_id)` — trust its verified hardware report, not the request.
   A quota or policy denial comes back as a structured outcome: report it, don't retry
   around it.

**Recovery**
- Session dropped mid-call → the tool returns `not_connected`; `open_notebook(id)`
  reconnects. URL-registered notebooks reopen where they were; `local_path` notebooks
  are restored from the last-synced local file (see above).
- Wrong/stale state → `restore_snapshot`, or `sync_notebook_to_colab` to reset from the
  repo file.
- Server-side confusion (ports, stale tabs) → the user runs `cool-colab-mcp doctor` /
  `--kill-stale`.

## Environment variables

| Variable | Meaning |
|---|---|
| `COOL_COLAB_MCP_NOTEBOOK_DIRS` | Allowlist for `local_path` registration |
| `COOL_COLAB_MCP_UPLOAD_DIRS` | Allowlist for upload sources |
| `COOL_COLAB_MCP_HOME` | State directory (default `~/.cool-colab-mcp`) |
| `COLAB_MCP_NOTEBOOK_URL` | Legacy default notebook when connecting without arguments |

## Pitfalls

- GitHub-URL notebooks (`/github/...`) load from the **remote branch** — local edits are
  invisible until pushed. Drive URLs preserve the live runtime across reconnects.
- Colab may omit outputs from `get_cells` after a run; the server caches live outputs and
  merges them into snapshots, exports, and local sync — so sync/export, don't scrape.
- Several notebooks can silently share one runtime assignment, and no tool maps
  endpoints to notebooks. Before treating GPU notebooks as independent, confirm the
  account lists as many distinct `assignment_endpoints` as you have notebooks — and
  involve the user in matching them.
- Destructive runtime tools refuse to act without `preservation_confirmed=True` and an
  explicit `assignment_endpoint` — that friction is intentional; satisfy it, don't
  bypass it.
- Auth problems (`user_action_required`) always need the human: browser sign-in or OAuth
  consent cannot be done by the agent. Relay the message's remedy and wait.
