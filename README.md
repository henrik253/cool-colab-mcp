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
| Multiple notebooks at once | No — one connection, one tab | One independent session per notebook |
| Survive restarts | No | Persistent auth, registry, and snapshots on disk |
| Save/restore notebook content | No | `.ipynb` snapshots with restore and export |
| Files into the runtime | Manual browser upload | Chunked upload to `/content` with SHA-256 verification |
| CPU/GPU switching | Removed upstream | OAuth runtime API (T4 / L4 / A100 / TPU) |
| Tools visible at startup | No — requires `tools/list_changed` | Pre-registered tool surface |
| Headless server operation | No | Managed Chromium via Playwright (Phase 2) |

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

```json
{
  "mcpServers": {
    "cool-colab-mcp": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/cool-colab-mcp", "colab-mcp"],
      "timeout": 30000
    }
  }
}
```

For development:

```bash
uv sync --group dev          # install deps
uv run pytest                # run tests
uv run pre-commit install    # once per clone
```

## Status

Early development — Phase 1 (registry, multi-session, snapshots, uploads, runtime control)
is being built feature by feature. See [docs/roadmap.md](docs/roadmap.md) for what works
today.

## Credits

- [googlecolab/colab-mcp](https://github.com/googlecolab/colab-mcp) — the upstream project
  and the browser-bridge protocol.
- [SebastianGilPinzon/colab-mcp](https://github.com/SebastianGilPinzon/colab-mcp) —
  reliability fixes and the OAuth `change_runtime` approach.
