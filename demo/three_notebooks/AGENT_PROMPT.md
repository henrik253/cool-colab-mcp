# Agent kickoff prompt

You are operating the self-contained three-notebook project in this directory through the
Cool Colab MCP server. Complete the live verification autonomously wherever safe, and stop only
for actions that genuinely require the user, such as Google consent, approving a Colab MCP
connection, identifying an ambiguous runtime assignment endpoint, or resolving Colab quota.

Your goal is to prove all of the following with three simultaneous, independently routed
notebook sessions:

- `demo-cpu-a` uses `notebooks/cpu-a.ipynb` and reports a CPU runtime;
- `demo-cpu-b` uses `notebooks/cpu-b.ipynb` and reports a CPU runtime;
- `demo-t4` uses `notebooks/t4.ipynb` and reports a T4 GPU runtime;
- `assets/test-upload.txt` reaches all three runtimes beneath their isolated
  `/content/cool-colab-demo/<notebook_id>/` destinations with size and SHA-256 verification;
- the final Colab cells are atomically synchronized back to all three local `.ipynb` files;
- OAuth credentials remain available after a separate-process restart without exposing tokens.

Working rules:

1. Read `README.md` and `config.local.json`. If the local config is missing, copy
   `config.example.json` and ask only for the OAuth client-secrets location.
2. Never print, read back, commit, or include OAuth tokens, cookies, client secrets, or browser
   profile data in your report.
3. Inspect the plan before mutating runtimes. Establish OAuth and verify persistence in a
   separate process.
4. Open all three notebooks concurrently and keep every tool call routed by its explicit
   `notebook_id`.
5. Before runtime replacement, confirm the notebook content is externally preserved. Never
   guess an assignment endpoint and never claim a requested GPU was granted until hardware
   verification identifies a T4.
6. Upload and verify the fixture independently in every runtime.
7. Call `sync_notebook_to_local` for every notebook before closing anything. Do not rely on
   `close_notebook` to save—it intentionally performs no implicit write.
8. Keep generated secrets and `config.local.json` uncommitted. Changes to the three tracked
   notebooks are expected and should be shown to the user for review.

Use `run_demo.py` as the reproducible harness, or invoke the equivalent MCP tools directly if
that provides better diagnostics. On completion, report a compact table containing notebook
ID, requested profile, verified accelerator, upload destination and verification result, local
sync path/result, plus the OAuth restart check. Clearly separate user-action requirements and
policy/quota denials from software failures.
