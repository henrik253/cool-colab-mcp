# Three-notebook agent demo

This folder is a self-contained example project that consumes Cool Colab MCP. It owns its
configuration, constants, notebooks, upload fixture, orchestration script, and agent prompt;
the `cool_colab_mcp` package contains no demo-specific behavior.

Copy `config.example.json` to `config.local.json`, place the OAuth desktop-client JSON at the
configured path, and never commit either secret-bearing file. Relative paths in the config are
resolved from this folder, so the demo can be copied to another repository.

For an autonomous run, give [`AGENT_PROMPT.md`](AGENT_PROMPT.md) to an MCP-enabled agent. For
manual verification, run these commands from any working directory:

```bash
uv run python /path/to/three_notebooks/run_demo.py plan --config /path/to/three_notebooks/config.local.json
uv run python /path/to/three_notebooks/run_demo.py auth --config /path/to/three_notebooks/config.local.json
uv run python /path/to/three_notebooks/run_demo.py auth-check --config /path/to/three_notebooks/config.local.json
uv run python /path/to/three_notebooks/run_demo.py login --config /path/to/three_notebooks/config.local.json
uv run python /path/to/three_notebooks/run_demo.py prepare --config /path/to/three_notebooks/config.local.json --auto-approve
uv run python /path/to/three_notebooks/run_demo.py configure --config /path/to/three_notebooks/config.local.json --auto-approve
uv run python /path/to/three_notebooks/run_demo.py verify-upload --config /path/to/three_notebooks/config.local.json --auto-approve
```

## Headless server (no display, no Chrome, no desktop)

Google refuses sign-in to automated browsers, but only *at sign-in*: a headless browser
holding an existing session is already authenticated. So a terminal-only server never signs
in — it replays a session exported from a machine with a display:

```bash
# on a machine with a display, once:
run_demo.py chrome --config config.local.json          # sign in to Google in that window
run_demo.py export-session --config config.local.json  # -> ~/.cool-colab-mcp/colab-session.json (0600)

# on the server:
uv sync && uv run playwright install chromium          # no Chrome, no Xvfb, no desktop
scp ~/.cool-colab-mcp/colab-session.json server:~/.cool-colab-mcp/
run_demo.py session-check --config config.local.json   # exit 0 = still signed in
run_demo.py prepare --config config.local.json \
    --auto-approve --headless --session-file ~/.cool-colab-mcp/colab-session.json
```

**The session file is a credential.** Its cookies authenticate as you with no password and no
2FA — treat it like a private key: keep it `0600`, never commit it, never bake it into an
image, and delete it when done. It is not the OAuth client JSON and not interchangeable with
it: the JSON identifies the *application*, the session identifies *you*.

Sessions expire (weeks, or instantly on a password change), so `export-session` is recurring
toil; `session-check` exits non-zero so a scheduler can alert instead of hanging. Two risks
worth knowing: Google may challenge a session that appears from a datacenter IP, and Device
Bound Session Credentials — which binds cookies to a machine's TPM — would end session
transfer entirely. The fallback then is Xvfb + noVNC on the server (Xvfb is a virtual
framebuffer, not a desktop environment), signing in on the box so the session originates
from its own IP.

## Unattended MCP approval

Colab always asks the user to accept a "Connect to a local Colab MCP server" dialog, and it
offers no "remember" option, so each phase would otherwise need three manual clicks. Passing
`--auto-approve` opens the notebook tabs in a managed Chromium that accepts the dialog itself
after verifying the dialog's token and port belong to that session (plan.md §11). Omit the flag
to keep the manual behaviour.

Signing in must happen in a **normally launched** browser: Playwright-launched browsers report
`navigator.webdriver`, and Google refuses sign-in to them. So use the `chrome` command, which
starts your real Chrome with no automation flags and its own profile (Chrome rejects remote
debugging on the default profile), then attach to it:

```bash
run_demo.py chrome --config config.local.json     # sign in to Google in that window
run_demo.py prepare --config config.local.json --auto-approve --cdp-url http://127.0.0.1:9222
```

Only you ever type your credentials. Keep the debug port bound to localhost and never expose
it — it grants full control of a signed-in browser.

`auth`/`auth-check` are a **separate** credential: the OAuth token for the runtime API, stored in
the OS keyring. The browser sign-in above is what lets the Colab frontend open notebooks and
runtimes.

The workflow opens three independent local-backed notebooks, requests two CPU runtimes and one
T4, uploads `assets/test-upload.txt` to each runtime, verifies the hardware and upload, and
atomically syncs each notebook back to its local `.ipynb`.

The folder's offline orchestration checks can be run independently with:

```bash
uv run pytest /path/to/three_notebooks/demo_test.py
```

Runtime replacement requires explicit assignment endpoints. `prepare` prints the available
endpoints; identify the endpoint belonging to each notebook and add it to `config.local.json`.
Do not guess: the wrong endpoint could stop another Colab runtime. GPU allocation can be denied
by Colab quota or policy, and the demo must report that outcome instead of bypassing it.

## Live verification findings

The July 2026 live run confirmed the following frontend/runtime contracts:

- `add_code_cell` requires numeric `cellIndex` and code `language`, and returns the new ID as
  `{"newCellId": "..."}`;
- OAuth runtime assignment routes are `/tun/m/...` on `colab.research.google.com` with
  `authuser=0`;
- Colab may return executed outputs from `run_code_cell` but omit them from a later `get_cells`;
  Cool Colab MCP caches those outputs per live session and merges them during local sync;
- three local files restored into scratch tabs can still map to one account assignment. Never
  reuse one endpoint for several notebook IDs or claim independent runtimes without observing
  distinct assignment endpoints.

The current command phases are one-shot processes, so tabs disconnect when a phase finishes.
A future persistent harness should keep one server alive across prepare, configure, upload,
sync, and reopen verification. With `--auto-approve` the repeated approvals are handled
automatically, so this is now a performance concern rather than a manual-clicking one.
