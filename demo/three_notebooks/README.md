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
uv run python /path/to/three_notebooks/run_demo.py prepare --config /path/to/three_notebooks/config.local.json
uv run python /path/to/three_notebooks/run_demo.py configure --config /path/to/three_notebooks/config.local.json
uv run python /path/to/three_notebooks/run_demo.py verify-upload --config /path/to/three_notebooks/config.local.json
```

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
sync, and reopen verification to require only one MCP approval per tab.
