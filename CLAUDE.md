# CLAUDE.md

Cool Colab MCP — an improved fork of Google's `colab-mcp` that turns Colab notebooks into
persistent, named, multi-session workspaces for AI agents.

**[docs/plan.md](docs/plan.md) is the source of truth** for architecture, features, and development
order. **[docs/roadmap.md](docs/roadmap.md) is the source of truth for progress** — what is done,
in progress, and which tests cover each feature. Keep it updated in the same branch as the feature
it describes.

All markdown documentation lives in `docs/`. The exceptions are README.md and CLAUDE.md at the
repo root (GitHub and Claude Code read them there), plus documentation owned by a self-contained,
copyable example project, which stays inside that example's directory.

## Commands

```bash
uv sync --group dev          # install deps
uv run pytest                # run all tests
uv run pytest tests/session_test.py -k name   # single test
uv run ruff check . && uv run ruff format .   # lint + format
uv run pre-commit install    # once per clone/worktree
```

Python 3.13, managed by `uv`. Never use `pip` directly.

## Code style

- **Minimalistic and clean.** No speculative abstractions, no dead code, no "just in case"
  parameters. If a feature needs 50 lines, don't write 150.
- Prefer small, focused modules over large ones. Follow the package layout in plan.md §16.
- **No constants inline in modules.** URLs, paths, ports, timeouts, magic strings, and state
  keys all live in `constants.py` — never scattered through the code.
- **Shared helpers go in utility modules** (`utils.py`), never copy-pasted between modules.
- Type hints everywhere; `pydantic` models for structured data crossing boundaries.
- Conventional commit messages (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`), as in the
  existing history.
- Colab-specific browser/UI code must be isolated under `browser/adapters/colab/` (plan.md §14)
  so Colab UI changes never touch registry, routing, or transfer code.

## Feature workflow

Every feature follows this exact loop:

1. **Pick** the next feature from roadmap.md (ordered by plan.md §17).
2. **Branch + worktree** (always branched from `integration`):
   `git worktree add ../cool-colab-mcp-worktrees/feature-<slug> -b feature/<slug> integration`
   Work only inside that worktree; never commit feature work directly on `main` or `integration`.
3. **Implement** the feature together with its tests. A feature without tests is not done.
4. **Update roadmap.md**: check off the feature's bullet points and list the test cases added.
5. **Verify locally**: `uv run pytest` (full suite) and `uv run ruff check .` must pass.
6. **Curate history**: squash WIP/fixup commits for the same coherent feature into one
   conventional commit. Keep distinct completed features as separate commits when one branch
   legitimately contains more than one feature.
7. **Review**: launch the `plan-reviewer` agent (`.claude/agents/plan-reviewer.md`) on every
   curated feature commit, or on the complete branch range when it contains multiple features.
   It critically compares the changes against plan.md. Address its findings before pushing.
8. **PR**: push the branch and open a PR against **`integration`** — feature PRs never target
   `main` directly. CI (ruff + full pytest suite) must be green before merging. Merge with
   **squash-merge** a single-feature PR. For a deliberately curated multi-feature PR, use a
   rebase merge so its distinct feature commits remain visible.
9. **Clean up**: `git worktree remove ../cool-colab-mcp-worktrees/feature-<slug>` and delete
   the branch.

### Integration → main

Feature PRs collect on the `integration` branch. When a development wave is complete, run the
`integration-refactorer` agent (`.claude/agents/integration-refactorer.md`) over the full
`main..integration` diff: it removes redundancy across features, simplifies, and keeps the
suite green. After its cleanup lands on `integration`, open a single PR `integration` → `main`
for user review.

## Testing

- Test files live in `tests/` and are named `<module>_test.py` (existing convention — not
  `test_<module>.py`).
- Async tests use `pytest-asyncio`.
- Unit tests must **never** contact real Colab, Google auth, or the network. Mock the
  WebSocket/browser boundary. If a real-Colab integration test is ever needed, mark it
  `@pytest.mark.integration` and keep it out of the default run.
- Every MCP tool gets tests for: happy path, bad `notebook_id`/input, and the failure path
  (e.g. disconnected session → structured error).

## Security rules (non-negotiable, from plan.md §3 and §14)

- Never log, return, or expose cookies, access tokens, or refresh tokens to connected agents.
- Credentials go in the OS keyring or encrypted local storage — never in the repo, config
  files, or test fixtures. Browser profile directories are gitignored.
- Expired/missing auth returns a structured `user_action_required` response; the same pattern
  applies to any browser-only action we can't automate.
- Never use private Colab APIs to bypass authentication, consent, quotas, or usage restrictions.

## Working with upstream

This is a fork of `googlecolab/colab-mcp`. Useful upstream fixes are cherry-picked manually
(the package will be renamed to `cool_colab_mcp`, so automatic merges won't apply cleanly).

`SebastianGilPinzon/colab-mcp` (Apache 2.0) is the reference fork for reliability fixes and
the OAuth-based `change_runtime` approach — cherry-pick with attribution; see plan.md
"Phase 1 Baseline" and §8.
