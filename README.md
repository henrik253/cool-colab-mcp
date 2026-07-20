# Cool Colab MCP

**An MCP server that turns Google Colab notebooks into persistent, named workspaces for AI
agents.**

With plain Colab MCP, your agent gets a temporary scratch notebook that is gone when the
browser tab closes. Cool Colab MCP makes notebooks durable resources instead: an agent can
register a notebook once, reopen it after any restart, keep several notebooks connected at
the same time, upload files straight into the runtime, and switch between CPU and GPU
runtimes — all without you clicking through the browser.

> Registered notebooks are persistent resources. Browser tabs, WebSocket connections, and
> Colab runtimes are replaceable sessions attached to them.

This is an improved fork of [googlecolab/colab-mcp](https://github.com/googlecolab/colab-mcp).

## What this fork adds

| Feature | Upstream | Cool Colab MCP |
|---|---|---|
| Reopen an existing notebook | No — always a blank scratch notebook | Per-connection `notebook_url`, notebook registry |
| Use repository `.ipynb` files | No | Local → Colab restore and atomic Colab → local sync |
| Multiple notebooks at once | No — one connection, one tab | One independent session per notebook |
| Survive restarts | No | Persistent auth, registry, and snapshots on disk |
| Save/restore notebook content | No | `.ipynb` snapshots with restore and export |
| Files into the runtime | Manual browser upload | Chunked upload to `/content` with SHA-256 verification |
| CPU/GPU switching | Removed upstream | OAuth runtime API (T4 / L4 / A100 / TPU) |
| Tools visible at startup | No — requires `tools/list_changed` | Pre-registered tool surface |
| Unattended operation | No — manual dialog click per connect | `--auto-approve` managed browser; headless via exported session file |

Reliability fixes are cherry-picked with attribution from the
[SebastianGilPinzon/colab-mcp](https://github.com/SebastianGilPinzon/colab-mcp) fork
(Apache 2.0).

## Architecture

The MCP server cannot control Colab directly — it bridges your local agent to the Colab
frontend running in a browser tab. Cool Colab MCP wraps that bridge in a management layer
and stamps out one complete session per notebook:

```text
AI Agent
   |
Cool Colab MCP
   |
   +-- Notebook Registry        names, URLs, preferred runtimes (persistent)
   +-- Session Manager          routes every tool call by notebook_id
   +-- Snapshot Manager         .ipynb snapshots on disk
   +-- Authentication Manager   keyring + persistent browser profile
   +-- File Transfer            chunked uploads into /content
   +-- Browser Controller       managed Chromium (Phase 2)
   |
   +-- NotebookSession A ── WebSocket A ── Colab tab A ── Runtime A (GPU)
   +-- NotebookSession B ── WebSocket B ── Colab tab B ── Runtime B (CPU)
```

Each `NotebookSession` owns its own browser tab, WebSocket server, token/port, proxy
client, and operation lock. The full design, feature specs, and development order live in
[docs/plan.md](docs/plan.md); progress is tracked in [docs/roadmap.md](docs/roadmap.md).

## Setup

Requires [uv](https://docs.astral.sh/uv/) and a local MCP client (Claude Code, Gemini CLI,
Cursor, ...).

```bash
git clone https://github.com/henrik253/cool-colab-mcp && cd cool-colab-mcp
uv sync
uv run playwright install chromium   # managed browser for --auto-approve
```

Register the server with your MCP client:

```json
{
  "mcpServers": {
    "cool-colab-mcp": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/cool-colab-mcp", "cool-colab-mcp"],
      "timeout": 30000
    }
  }
}
```

Useful additional `args`: `--auto-approve` (connect without clicking Colab's MCP dialog —
see below), `--client-oauth-config <json>` (runtime switching), `-v` and `--log <dir>`
(debugging).

### One-time authentication

Two independent credentials, both optional until the feature that needs them is used:

1. **Google browser session** — lets notebook tabs open already signed in. Google refuses
   sign-in inside automated browsers, so sign in once in a normally launched Chrome with a
   debug port, then let the managed browser attach to it:

   ```bash
   # macOS
   open -na "Google Chrome" --args --remote-debugging-port=9222 \
       --user-data-dir=$HOME/.cool-colab-mcp/chrome-profile
   # Linux
   google-chrome --remote-debugging-port=9222 \
       --user-data-dir=$HOME/.cool-colab-mcp/chrome-profile
   ```

   Sign in to Google in that window, then run the server with
   `--auto-approve --cdp-url http://127.0.0.1:9222`. Chrome rejects remote debugging on
   the default profile, hence the dedicated one. Keep port 9222 bound to localhost: it
   grants full control of a signed-in browser.

2. **Runtime-API OAuth token** — only needed for CPU/GPU switching. Create an OAuth
   client of type *Desktop app* in the Google Cloud Console, download its client-secrets
   JSON, and pass it via `--client-oauth-config`. The first runtime-switching call
   returns a structured `user_action_required` explaining the consent step; the demo's `auth`
   command runs that consent flow interactively. The token is stored in the OS keyring
   and refreshes itself.

### Unattended and headless servers

Colab asks for approval of every MCP connection and offers no "remember" option.
`--auto-approve` opens notebook tabs in a managed browser that accepts the dialog itself —
after verifying that the dialog's token and port belong to this server, never blindly.

A machine with no display never signs in — it replays a session exported from one that
did: run the demo's `export-session` on the signed-in machine, copy
`~/.cool-colab-mcp/colab-session.json` to the server (keep it `0600`; it authenticates as
you with no password or 2FA), then start the server with
`--auto-approve --headless --session-file ~/.cool-colab-mcp/colab-session.json`.
No Chrome, Xvfb, or desktop is needed. Sessions expire after weeks (or on a password
change); the full recipe and caveats are in the
[three-notebook demo](demo/three_notebooks/README.md).

### Remote Linux desktops (xrdp, VNC, SSH)

- On software-rendered displays, launch your Chrome with `--disable-gpu`; without it
  Chrome's GPU process can hang and freeze the whole desktop.
- From an SSH shell, export `DISPLAY`, `XAUTHORITY`, and `DBUS_SESSION_BUS_ADDRESS` from
  the active desktop session first — otherwise the OS keyring reports unavailable and
  browser windows open where nobody can see them.
- A crashed desktop session can lose the keyring-stored OAuth token; re-running the
  consent flow restores it.

### Maintenance

`uv run cool-colab-mcp doctor` checks config, storage, ports, and stale servers with a
fix hint per failure; `--list-running` and `--kill-stale` inspect and clean up leftover
server processes.

For development:

```bash
uv sync --group dev          # install deps
uv run pytest                # run tests
uv run pre-commit install    # once per clone
```

To use notebooks directly from a repository, allow only that repository (or its notebook
directory), register the local path, and sync back before closing the session:

```bash
export COOL_COLAB_MCP_NOTEBOOK_DIRS=/absolute/path/to/project
```

Call `register_notebook` with `local_path=/absolute/path/to/project/notebooks/job.ipynb`.
`open_notebook` opens a scratch Colab tab and restores that file into it. After editing or
running cells, call `sync_notebook_to_local`; the registered `.ipynb` is replaced atomically.
Use `sync_notebook_to_colab` to explicitly discard the tab's cells and reload the local file.
`close_notebook` intentionally does not sync, so an accidental close cannot overwrite local
work.

To exercise three simultaneous notebooks, persistent OAuth, CPU/T4 runtime control, and
verified uploads before deployment, follow the
[self-contained three-notebook agent demo](demo/three_notebooks/README.md).

## Status

Early development — Phase 1 (registry, multi-session, snapshots, uploads, runtime control)
is being built feature by feature. See [docs/roadmap.md](docs/roadmap.md) for what works
today.

## Credits

- [googlecolab/colab-mcp](https://github.com/googlecolab/colab-mcp) — the upstream project
  and the browser-bridge protocol.
- [SebastianGilPinzon/colab-mcp](https://github.com/SebastianGilPinzon/colab-mcp) —
  reliability fixes and the OAuth `change_runtime` approach.
