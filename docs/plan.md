# Cool Colab MCP — Project Plan

> **Repository:** `cool-colab-mcp`  
> **Description:** An improved fork of Colab MCP for persistent, multi-notebook, agent-controlled Google Colab workflows.

## 1. Goal

Cool Colab MCP should allow an AI agent to treat Colab notebooks as persistent workspaces instead of temporary browser sessions.

The project should support:

- persistent Google authentication;
- reopening existing notebooks;
- saving and restoring notebook content;
- multiple active notebooks;
- direct file uploads into Colab runtimes;
- CPU/GPU runtime lifecycle management;
- unattended operation on a headless server.

## 2. Architecture

The current Colab MCP flow is:

```text
AI Agent
   |
Local MCP Server
   |
WebSocket
   |
Open Colab Browser Tab
   |
Colab Notebook and Runtime
```

The local MCP server does not directly control the Colab backend. It forwards commands to the Colab frontend running in an open browser page.

Cool Colab MCP will add a management layer around this connection:

```text
AI Agent
   |
Cool Colab MCP
   |
   +-- Notebook Registry
   +-- Session Manager
   +-- Snapshot Manager
   +-- Authentication Manager
   +-- File Transfer
   +-- Browser Controller
   |
   +-- Notebook A / WebSocket A
   +-- Notebook B / WebSocket B
```

Each notebook must have its own browser page, WebSocket connection, proxy client, and operation queue.

---

# Phase 1 — Core Features

Phase 1 contains the features that can be implemented mainly through the existing Colab MCP connection, persistent local state, and code execution inside the notebook.

## Baseline — Upstream Reliability Fixes

Before building new features, port the verified fixes from the
[SebastianGilPinzon/colab-mcp](https://github.com/SebastianGilPinzon/colab-mcp) fork
(Apache 2.0 — cherry-pick with attribution). These fix upstream bugs that block
day-to-day use and that every Phase 1 feature builds on:

- pre-register all notebook tools at startup (most MCP clients ignore
  `notifications/tools/list_changed`; without this the bridge is effectively write-only);
- "Disconnected" fixes: IPv4/IPv6 dual-stack bind, Private Network Access CORS headers,
  and a unique `?p=<port>` query param on the notebook URL so Chrome cannot reuse a stale
  tab pointing at a dead server;
- corrected Colab API signatures (`run_code_cell` with `cellId`, `move_cell`,
  `ColabClient` initialization with an explicit environment);
- stale-server process registry with detection and cleanup (`--list-running`,
  `--kill-stale`, pruning on startup) — this feeds directly into the `doctor` command.

## Per-Connection Notebook Targeting

### Problem

Upstream hardcodes `SCRATCH_PATH = "/notebooks/empty.ipynb"` (`session.py`,
`check_session_proxy_tool_fn`), so every `open_colab_browser_connection` — including
automatic reconnects after a dropped WebSocket — opens a new blank scratch notebook,
abandoning the notebook and runtime the user was working in (upstream discussion #80,
unresolved). The interim env-var fix (`COLAB_MCP_NOTEBOOK_URL`) pins reconnects to one
notebook, but it binds a connection-time decision to process-start configuration: the
env is read once at server launch, so switching notebooks requires editing the client
config and restarting the MCP server — disruptive mid-session, and easy to forget (the
connection silently opens the wrong notebook).

### Implementation

Add an optional `notebook_url` parameter to `open_colab_browser_connection`:

- `open_colab_browser_connection(notebook_url=...)` → open that notebook and remember it
  as the session's active notebook;
- no parameter → fall back to (1) the active notebook from the current session (so
  reconnects return to where you were), then (2) the `COLAB_MCP_NOTEBOOK_URL` env
  default, then (3) scratch, in that order.

Accept both URL forms:

- GitHub-backed (`colab.research.google.com/github/...`) — deterministic reload from a
  branch, fresh runtime;
- Drive (`colab.research.google.com/drive/<FILE_ID>`) — preserves the live runtime
  across reconnects.

### Why this layer

The proxy `token`/`port` (stable for the MCP process lifetime) already reattach to any
Colab tab whose URL carries the `#mcpProxyToken=…&mcpProxyPort=…` fragment — the server
genuinely doesn't care which notebook is loaded. The notebook choice is purely a
browser-navigation argument, so it belongs in the tool call, not the process
environment. The registry's `open_notebook` (section 4) builds on this layer.

### Acceptance criteria

- Switching notebooks between connections requires no config edit and no server restart.
- Reconnect after a WebSocket drop reopens the notebook that was active, not scratch.
- The env pin still works as the default for headless/legacy callers.
- The tool description documents the GitHub-URL caveat: content loads from the remote
  branch, so local edits must be pushed to be visible.

## 3. Persistent Authentication

### Goal

Allow the service to restart without requiring the user to log in every time.

### Implementation

- Use a persistent Chromium profile for the Google and Colab browser session.
- Optionally store a Google Drive OAuth refresh token for Drive API operations.
- Store the OAuth token for the Colab runtime API (see section 8) the same way — the
  reference fork caches it as plaintext JSON (`~/.colab-mcp-auth-token.json`); we harden
  this to keyring or encrypted storage.
- Store credentials using the operating-system keyring or encrypted local storage.
- Never expose cookies, access tokens, or refresh tokens to connected agents.
- Detect expired authentication and return a structured `user_action_required` response.

### Limitation

Google may still occasionally require manual login, consent, or security verification.

## 4. Notebook Registry

### Goal

Open a previously registered notebook instead of always creating a new empty notebook.

### Notebook record

```json
{
  "notebook_id": "yourmt3-training",
  "name": "YourMT3+ Training",
  "url": "https://colab.research.google.com/drive/FILE_ID",
  "preferred_runtime": "gpu"
}
```

### Required tools

```text
register_notebook
list_notebooks
open_notebook
close_notebook
remove_notebook
get_notebook_status
```

### Expected behavior

The notebook URL and metadata remain available after restarting the MCP server, browser, or host machine.

`open_notebook` resolves the registered URL and opens it through the per-connection
targeting layer (`notebook_url`, see "Per-Connection Notebook Targeting").

## 5. Notebook State and Snapshots

### Goal

Preserve notebook content and make recovery possible.

### Store

- code cells;
- markdown cells;
- cell order;
- cell metadata;
- outputs where available;
- environment setup instructions;
- Git repository and commit information;
- checkpoint and artifact paths.

### Required tools

```text
create_snapshot
list_snapshots
restore_snapshot
export_notebook
```

Snapshots should be saved as valid `.ipynb` files.

### Limitation

The project cannot permanently preserve arbitrary live runtime state such as:

- Python objects in RAM;
- CUDA memory;
- running processes;
- temporary `/content` files after the VM is deleted.

Runtime state must instead be restored through setup scripts, environment manifests, and checkpoints.

## 6. Multiple Notebook Sessions

### Goal

Run and control several notebooks simultaneously.

### Implementation

Create one independent session per notebook:

```text
NotebookSession
├── notebook_id
├── browser page
├── WebSocket server
├── token and port
├── MCP proxy client
└── operation lock
```

Do not remove the current single-connection lock and share the same streams. Instead, create multiple complete WebSocket server instances.

### Tool routing

Every notebook-specific tool must receive a `notebook_id`:

```text
get_cells(notebook_id)
run_cell(notebook_id, cell_id)
update_cell(notebook_id, cell_id, source)
```

Operations may run concurrently across different notebooks. Writes inside the same notebook should initially be serialized.

## 7. Direct File Upload

### Goal

Upload files directly into an active Colab runtime without storing them in Google Drive.

### Phase 1 implementation

- Read the file on the host.
- Split it into chunks.
- Transfer the chunks through notebook code execution.
- Reconstruct the file under `/content`.
- Verify the final file using size and SHA-256.
- Delete incomplete files after failed uploads.

### Required tools

```text
upload_file
upload_directory
get_upload_status
cancel_upload
list_runtime_files
```

Host file access must be restricted to configured directories.

### Limitation

Files stored only in `/content` disappear when the Colab runtime is deleted.

## 8. Runtime State and Profiles

### Goal

Provide a consistent interface for CPU and GPU workflows.

### Required tools

```text
get_runtime_status
connect_runtime
disconnect_runtime
stop_runtime
restart_runtime
request_runtime_profile
```

### Example profiles

```text
prototype-cpu
debug-gpu
training-gpu
```

Before stopping a runtime, the system should:

1. save the notebook;
2. create a snapshot;
3. save selected logs and checkpoints;
4. store the environment reconstruction manifest.

After a new runtime connects, the system should:

1. verify the actual hardware;
2. reinstall dependencies;
3. restore project files;
4. restore the latest checkpoint;
5. report whether the requested profile was satisfied.

### Implementation

Runtime-type changes use the OAuth-authenticated Colab runtime API
(`colab.pa.googleapis.com`), as proven by the reference fork's `change_runtime` tool.
It supports assigning T4 / L4 / A100 / TPU variants or NONE (CPU) and surfaces quota
and denial outcomes (`QUOTA_DENIED`, `DENYLISTED`, ...) as structured results. Browser
automation is **not** required for runtime switching — this moves CPU/GPU switching
from Phase 2 into Phase 1.

### Phase 1 limitation

The runtime API requires a one-time, user-created GCP OAuth client (roughly 5 minutes of
manual Cloud Console setup; Google offers no API for creating OAuth clients). Runtime
actions the API does not expose still return `user_action_required`.

## 9. Phase 1 Acceptance Criteria

Phase 1 is complete when:

1. Authentication survives a normal restart.
2. An existing Drive-backed notebook can be registered and reopened.
3. The same notebook is reopened instead of a new scratch notebook — including automatic reconnects after a dropped WebSocket.
4. Notebook snapshots can be created and restored.
5. At least two notebooks can remain connected simultaneously.
6. Commands and responses are routed to the correct notebook.
7. Files can be uploaded directly into `/content`.
8. Runtime CPU/GPU status can be detected, and a GPU/CPU runtime can be requested through the runtime API.
9. Unsupported browser-only actions return `user_action_required`.
10. Restarting the MCP server does not delete the notebook registry or snapshots.

---

# Phase 2 — Browser Automation

Phase 2 removes the remaining routine user interaction by controlling the Colab browser independently of the notebook MCP connection.

## 10. Managed Browser

### Technology

Use:

- Playwright;
- Chromium with a persistent profile;
- Chrome DevTools Protocol where required;
- Xvfb on headless Linux servers;
- optional noVNC for first login and recovery.

### Features

- start and supervise Chromium;
- reopen registered notebook tabs;
- map each tab to a `notebook_id`;
- recover tabs after a browser crash;
- detect login, consent, and error pages;
- reconnect notebook sessions automatically.

## 11. Automatic MCP Approval

### Goal

Automatically accept the Colab popup that enables the MCP WebSocket connection.

The notebook MCP itself cannot click this popup because the connection is not active yet.

### Browser controller behavior

Before accepting, verify:

- the page is hosted on the expected Colab origin;
- the notebook matches the requested `notebook_id`;
- the WebSocket token and port match the created session;
- the connection was initiated by Cool Colab MCP.

Then:

1. detect the approval popup;
2. click the correct approval button;
3. wait for the WebSocket connection;
4. retry with bounded backoff;
5. report a clear error if the Colab UI has changed.

The controller must never click generic approval or consent buttons without verification.

## 12. Automated Runtime-Switch Orchestration

### Goal

Allow an agent to move from a CPU prototyping runtime to a GPU training runtime without
losing work.

The runtime switch itself is an OAuth API call (section 8) and needs no browser
automation. Phase 2 automates the orchestration around it:

1. Save the notebook and create a snapshot.
2. Request the new runtime through the runtime API.
3. Reconnect the notebook session to the new runtime.
4. Verify actual hardware from Python.
5. Run the environment bootstrap.
6. Restore checkpoints.
7. Continue the workflow.

### Limitation

Cool Colab MCP can request GPU access, but it cannot guarantee:

- GPU availability;
- a specific GPU model;
- multiple simultaneous GPU runtimes;
- that Colab will not terminate the runtime.

## 13. Faster File Uploads

Phase 2 may add a browser-native upload method for larger files.

Possible approaches:

- Colab file-upload controls;
- browser drag-and-drop;
- a temporary authenticated transfer service;
- a stable frontend upload API, if one is available.

The Phase 1 chunked upload remains the fallback.

## 14. JavaScript and Private Frontend APIs

JavaScript or undocumented Colab frontend APIs should be used only when normal browser automation is insufficient.

All Colab-specific browser code should be isolated under:

```text
src/cool_colab_mcp/browser/adapters/colab/
```

This prevents Colab UI changes from affecting notebook persistence, routing, or file-transfer components.

Private APIs must not be used to bypass:

- authentication;
- consent;
- quotas;
- security checks;
- Colab usage restrictions.

## 15. Phase 2 Acceptance Criteria

Phase 2 is complete when:

1. Cool Colab MCP runs on a headless Linux server.
2. Chromium starts automatically with the saved profile.
3. Registered notebook tabs are restored.
4. Verified MCP connection popups are accepted automatically.
5. Disconnected frontend sessions reconnect automatically.
6. An agent can request CPU or GPU runtime profiles.
7. Actual hardware is verified after connection.
8. The environment and checkpoint are restored after runtime replacement.
9. Browser UI changes fail safely with a clear error.
10. Manual interaction is only required for Google security or policy-required prompts.

---

# 16. Suggested Repository Structure

```text
docs/                  # all markdown docs (plan, roadmap, contributing)
src/cool_colab_mcp/
├── server.py
├── config.py
├── constants.py       # all constants, URLs, paths — never inline in modules
├── utils.py           # shared helpers
├── auth/
├── registry/
├── sessions/
├── notebooks/
├── runtime/
├── transfer/
├── browser/
│   └── adapters/colab/
├── cli/
└── tests/
```

# 17. Development Order

1. Fork and reproduce the upstream workflow.
2. Port the upstream reliability fixes (Phase 1 Baseline).
3. Add per-connection notebook targeting (`notebook_url` parameter).
4. Add structured logging and `doctor`.
5. Implement the notebook registry (`open_notebook` builds on notebook targeting).
6. Extract a reusable `NotebookSession`.
7. Add multi-notebook routing.
8. Add notebook snapshots.
9. Add persistent authentication storage.
10. Add direct file uploads.
11. Add runtime status, profiles, and API-based CPU/GPU switching.
12. Add Playwright browser management.
13. Automate MCP popup approval.
14. Automate runtime-switch orchestration (snapshot → switch → verify → restore).
15. Add headless deployment and recovery.

# 18. Definition of Success

Cool Colab MCP succeeds when an AI agent can treat Colab notebooks as persistent, named, and independently managed workspaces.

> Registered notebooks are persistent resources. Browser tabs, WebSocket connections, and Colab runtimes are replaceable sessions attached to them.
