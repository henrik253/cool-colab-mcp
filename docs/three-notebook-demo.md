# Three-notebook live demo

This demo exercises three simultaneous named Colab sessions, persistent OAuth credentials,
runtime-profile control, and verified host-to-runtime file uploads. It requests two CPU
runtimes and one T4 GPU runtime.

## Prerequisites

1. Create three Colab notebooks in Google Drive and copy their full Colab URLs.
2. Create a Google OAuth client of type **Desktop app**, download its client-secrets JSON,
   and keep it outside this repository.
3. Copy `demo/three_notebooks/config.example.json` to
   `demo/three_notebooks/config.local.json`. Replace the three URLs and OAuth path.
4. Run from the repository root with Python 3.13 through `uv`.

Never commit `config.local.json`, OAuth client secrets, cookies, or tokens.

## 1. Inspect the plan

```bash
uv run python demo/three_notebooks/run_demo.py plan \
  --config demo/three_notebooks/config.local.json
```

The configuration validator requires exactly three unique notebook IDs, two
`prototype-cpu` profiles, and one `debug-gpu` profile.

## 2. Establish and verify persistent authentication

The first command opens Google's interactive consent flow and stores the resulting token in
the OS keyring:

```bash
uv run python demo/three_notebooks/run_demo.py auth \
  --config demo/three_notebooks/config.local.json
```

Run this as a separate process to prove the credentials survive restart:

```bash
uv run python demo/three_notebooks/run_demo.py auth-check \
  --config demo/three_notebooks/config.local.json
```

The command prints only validity state, never token values.

## 3. Register and open all three notebooks

```bash
uv run python demo/three_notebooks/run_demo.py prepare \
  --config demo/three_notebooks/config.local.json
```

Three browser tabs open concurrently. Approve the Colab MCP connection prompt in every tab.
The command reports each actual runtime and the account's assignment endpoints.

Runtime replacement deliberately requires an explicit endpoint because guessing could stop
another notebook's VM. Match each endpoint to its notebook. If the account already has other
assignments, isolate the mapping by closing unrelated Colab runtimes or observing the endpoint
set before and after opening one demo notebook. Put the three confirmed endpoints into
`config.local.json`.

## 4. Request two CPU runtimes and one T4 runtime

Before this destructive step, save the notebooks and any files or checkpoints that matter.
The demo passes `preservation_confirmed=true` and Cool Colab MCP generates a package manifest;
automatic snapshot/restore orchestration is not implemented yet.

```bash
uv run python demo/three_notebooks/run_demo.py configure \
  --config demo/three_notebooks/config.local.json
```

The two `prototype-cpu` entries request accelerator `NONE`; `debug-gpu` requests `T4`.
Colab replaces the runtimes, so allow the tabs to reconnect before the final phase.

## 5. Verify runtimes and upload the shared file

```bash
uv run python demo/three_notebooks/run_demo.py verify-upload \
  --config demo/three_notebooks/config.local.json
```

This phase reopens all three named sessions, calls `connect_runtime`, uploads
`demo/three_notebooks/assets/test-upload.txt` independently to each runtime, verifies its size
and SHA-256, and lists its destination directory. Expected destinations are:

```text
/content/cool-colab-demo/demo-cpu-a/test-upload.txt
/content/cool-colab-demo/demo-cpu-b/test-upload.txt
/content/cool-colab-demo/demo-t4/test-upload.txt
```

The command fails unless the first two runtime reports resolve to CPU, the third identifies a
T4, and every upload reports verified completion. Colab quota or account policy may deny T4
allocation; that is returned as `user_action_required` rather than bypassed.
