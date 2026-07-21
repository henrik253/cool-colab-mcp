"""Live three-notebook demo for registry, auth, runtime control, and uploads."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Literal

from fastmcp import Client
from pydantic import BaseModel, field_validator, model_validator

from cool_colab_mcp.auth import ensure_credentials, run_consent_flow
from cool_colab_mcp.browser.controller import BrowserController
from constants import (
    COMMANDS,
    CPU_COUNT,
    CPU_PROFILE,
    GPU_COUNT,
    GPU_PROFILE,
    NOTEBOOK_COUNT,
    NOTEBOOK_DIRS_ENV,
    NOTEBOOK_SUFFIX,
    PLACEHOLDER_MARKER,
    LOGIN_POLL_S,
    LOGIN_TIMEOUT_S,
    APP_READY_MARKERS,
    CDP_URL,
    CHROME_APP,
    CHROME_DEBUG_PORT,
    CHROME_LINUX_BIN,
    CHROME_PROFILE_DIR,
    RUNTIME_DIR,
    SESSION_CHECK_POLLS,
    RUNTIME_PROFILES,
    SIGN_IN_MARKER,
    UPLOAD_DIRS_ENV,
    UPLOAD_FILENAME,
)
from cool_colab_mcp.constants import (
    BROWSER_PROFILE_DIR_NAME,
    COLAB,
    SCRATCH_PATH,
    SESSION_FILE_NAME,
)
from cool_colab_mcp.runtime.client import RuntimeClient
from cool_colab_mcp.server import build_server
from cool_colab_mcp.sessions.manager import SessionManager
from cool_colab_mcp.storage import base_dir

DEMO_DIR = Path(__file__).resolve().parent
UPLOAD_FILE = DEMO_DIR / "assets" / "test-upload.txt"


class NotebookConfig(BaseModel):
    notebook_id: str
    name: str
    local_path: Path
    runtime_profile: Literal[CPU_PROFILE, GPU_PROFILE]
    assignment_endpoint: str | None = None

    @field_validator("notebook_id", "name")
    @classmethod
    def non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("local_path")
    @classmethod
    def local_notebook(cls, value: Path) -> Path:
        if value.suffix != NOTEBOOK_SUFFIX:
            raise ValueError(f"local_path must end with {NOTEBOOK_SUFFIX}")
        if PLACEHOLDER_MARKER in str(value):
            raise ValueError("replace the example local notebook path")
        return value


class DemoConfig(BaseModel):
    oauth_config_path: Path
    notebooks: list[NotebookConfig]

    @model_validator(mode="after")
    def distinct_notebooks(self) -> "DemoConfig":
        if not 1 <= len(self.notebooks) <= NOTEBOOK_COUNT:
            raise ValueError("the demo requires one to three notebooks")
        ids = [notebook.notebook_id for notebook in self.notebooks]
        if len(set(ids)) != len(ids):
            raise ValueError("notebook_id values must be unique")
        profiles = [notebook.runtime_profile for notebook in self.notebooks]
        if (
            profiles.count(CPU_PROFILE) > CPU_COUNT
            or profiles.count(GPU_PROFILE) > GPU_COUNT
        ):
            raise ValueError("at most two prototype-cpu and one debug-gpu")
        return self


def load_config(path: Path) -> DemoConfig:
    data = json.loads(path.read_text())
    base = path.resolve().parent
    oauth_path = Path(data["oauth_config_path"]).expanduser()
    if not oauth_path.is_absolute():
        data["oauth_config_path"] = str(base / oauth_path)
    for notebook in data["notebooks"]:
        local_path = Path(notebook["local_path"]).expanduser()
        if not local_path.is_absolute():
            notebook["local_path"] = str(base / local_path)
    return DemoConfig.model_validate(data)


def plan(config: DemoConfig) -> list[dict[str, str | None]]:
    return [
        {
            "notebook_id": notebook.notebook_id,
            "local_path": str(notebook.local_path),
            "runtime_profile": notebook.runtime_profile,
            "assignment_endpoint": notebook.assignment_endpoint,
            "upload_destination": destination(notebook),
        }
        for notebook in config.notebooks
    ]


def destination(notebook: NotebookConfig) -> str:
    return f"{RUNTIME_DIR}/{notebook.notebook_id}/{UPLOAD_FILENAME}"


def authenticate(config: DemoConfig) -> None:
    run_consent_flow(config.oauth_config_path)
    print("OAuth consent completed; credentials are stored in the OS keyring.")


def check_auth(config: DemoConfig) -> None:
    credentials = ensure_credentials(config.oauth_config_path)
    print(f"Persistent OAuth credentials available: valid={credentials.valid}")


def assignments(config: DemoConfig) -> None:
    credentials = ensure_credentials(config.oauth_config_path)
    records = RuntimeClient(credentials).list_assignments()
    safe = [{"endpoint": record["endpoint"]} for record in records]
    print(json.dumps({"assignments": safe}, indent=2))


def launch_chrome() -> None:
    """Start the operator's own Chrome with a debug port, then let them sign in.

    Playwright-launched browsers report navigator.webdriver, and Google refuses
    sign-in to them. This Chrome is launched normally — no automation flags — so
    signing in works; the demo attaches to it afterwards with --cdp-url. Chrome
    rejects remote debugging on the default profile, hence the dedicated one.
    """
    profile = base_dir() / CHROME_PROFILE_DIR
    profile.mkdir(parents=True, exist_ok=True)
    chrome_args = [
        f"--remote-debugging-port={CHROME_DEBUG_PORT}",
        f"--user-data-dir={profile}",
        f"{COLAB}{SCRATCH_PATH}",
    ]
    if sys.platform == "darwin":
        subprocess.run(["open", "-na", CHROME_APP, "--args", *chrome_args], check=True)
    else:
        # Detach so Chrome outlives this one-shot command.
        subprocess.Popen(
            [CHROME_LINUX_BIN, *chrome_args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    print(
        f"Chrome launched with its own profile at {profile}.\n"
        "Sign in to Google in that window (it is a normal Chrome, so sign-in "
        "works), then run the live phases with:\n"
        f"  --auto-approve --cdp-url {CDP_URL}",
        flush=True,
    )


def session_path(explicit: str | None) -> Path:
    return Path(explicit) if explicit else base_dir() / SESSION_FILE_NAME


async def export_session(cdp_url: str, path: Path) -> None:
    """Copy the session out of the Chrome you signed into, for a headless server.

    The file authenticates as you with no password or 2FA. Keep it 0600, never
    commit it, and re-export when it expires.
    """
    browser = BrowserController(cdp_url=cdp_url)
    await browser.start()
    try:
        count = await browser.export_session(path)
        print(
            f"Exported {count} cookies to {path} (mode 0600).\n"
            "This file authenticates as you: copy it to the server over scp, keep "
            "it out of git and images, and re-export when it stops working.",
            flush=True,
        )
    finally:
        await browser.aclose()


async def session_check(path: Path, headless: bool = True) -> bool:
    """Report whether an exported session still signs in, before a run depends on it."""
    browser = BrowserController(headless=headless, session_file=path)
    await browser.start()
    try:
        page = await browser.open_page(f"{COLAB}{SCRATCH_PATH}")
        for _ in range(SESSION_CHECK_POLLS):
            if await signed_in(page):
                print(f"Session at {path}: valid (signed in).", flush=True)
                return True
            await asyncio.sleep(LOGIN_POLL_S)
        print(
            f"Session at {path}: EXPIRED or invalid. Re-run 'chrome', sign in, "
            "then 'export-session'.",
            flush=True,
        )
        return False
    finally:
        await browser.aclose()


class WindowClosed(RuntimeError):
    """The operator closed the sign-in window."""


async def signed_in(page) -> bool:
    """Whether Colab shows a signed-in session.

    Only meaningful once the app shell has rendered: a blank page trivially lacks the
    sign-in prompt, so checking too early reports success for a signed-out profile.
    """
    try:
        text = await page.evaluate("(document.body.innerText||'')")
    except Exception as exc:  # the window went away mid-poll
        if "closed" in str(exc).lower():
            raise WindowClosed(str(exc)) from None
        raise
    if not all(marker in text for marker in APP_READY_MARKERS):
        return False
    return SIGN_IN_MARKER not in text


async def browser_login() -> bool:
    """Open the managed browser so the operator signs in to Google once.

    This browser is NOT the operator's everyday Chrome: it keeps its own persistent
    profile, so the sign-in must happen in this window. Afterwards --auto-approve runs
    are unattended. Only the operator ever types their credentials.
    """
    browser = BrowserController(headless=False)
    await browser.start()
    try:
        page = await browser.open_page(f"{COLAB}{SCRATCH_PATH}")
        print(
            "A Colab window is open. This is a separate browser from your everyday "
            "Chrome, so sign in to Google inside that window.\n"
            f"Waiting up to {LOGIN_TIMEOUT_S}s; the window closes once sign-in is "
            "detected.",
            flush=True,
        )
        deadline = asyncio.get_running_loop().time() + LOGIN_TIMEOUT_S
        while asyncio.get_running_loop().time() < deadline:
            try:
                if await signed_in(page):
                    print(
                        "Signed in. The session is stored in the browser profile at "
                        f"{base_dir() / BROWSER_PROFILE_DIR_NAME}",
                        flush=True,
                    )
                    return True
            except WindowClosed:
                print(
                    "The sign-in window was closed before sign-in completed; "
                    "re-run 'login' and leave the window open.",
                    flush=True,
                )
                return False
            await asyncio.sleep(LOGIN_POLL_S)
        print("Timed out waiting for sign-in; re-run 'login' to try again.", flush=True)
        return False
    finally:
        await browser.aclose()


async def call(client: Client, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await client.call_tool(tool, arguments)
    payload = result.structured_content or {}
    if "error" in payload:
        error = payload["error"]
        raise RuntimeError(f"{tool}: {error['kind']}: {error['message']}")
    return payload


async def clients(server, count: int, stack: AsyncExitStack) -> list[Client]:
    return [await stack.enter_async_context(Client(server)) for _ in range(count)]


async def register_and_open(config: DemoConfig, mcp_clients: list[Client]) -> None:
    for client, notebook in zip(mcp_clients, config.notebooks, strict=True):
        await call(
            client,
            "register_notebook",
            {
                "notebook_id": notebook.notebook_id,
                "name": notebook.name,
                "local_path": str(notebook.local_path),
                "preferred_runtime": notebook.runtime_profile,
            },
        )
    # One tab at a time: opening all notebooks concurrently can overwhelm the
    # browser on machines without GPU rendering (the MCP dialog then never
    # becomes clickable and the whole desktop may freeze).
    for client, notebook in zip(mcp_clients, config.notebooks, strict=True):
        await call(client, "open_notebook", {"notebook_id": notebook.notebook_id})


async def configure_runtimes(
    config: DemoConfig, mcp_clients: list[Client]
) -> list[dict[str, Any]]:
    missing = [
        notebook.notebook_id
        for notebook in config.notebooks
        if not notebook.assignment_endpoint
    ]
    if missing:
        raise RuntimeError(
            "assignment_endpoint is required for configure: " + ", ".join(missing)
        )
    results = []
    for client, notebook in zip(mcp_clients, config.notebooks, strict=True):
        results.append(
            await call(
                client,
                "request_runtime_profile",
                {
                    "notebook_id": notebook.notebook_id,
                    "profile": notebook.runtime_profile,
                    "assignment_endpoint": notebook.assignment_endpoint,
                    "preservation_confirmed": True,
                },
            )
        )
    return results


def _accelerator_in(value: Any) -> str | None:
    if isinstance(value, dict):
        accelerator = value.get("accelerator")
        if isinstance(accelerator, str):
            return accelerator
        for child in value.values():
            if found := _accelerator_in(child):
                return found
    elif isinstance(value, list):
        for child in value:
            if found := _accelerator_in(child):
                return found
    elif isinstance(value, str):
        try:
            return _accelerator_in(json.loads(value))
        except json.JSONDecodeError:
            return None
    return None


def verify_hardware(notebook: NotebookConfig, runtime: dict[str, Any]) -> None:
    actual = _accelerator_in(runtime)
    expected = RUNTIME_PROFILES[notebook.runtime_profile]
    matches = (
        actual == "CPU"
        if expected == "NONE"
        else actual is not None and expected in actual
    )
    if not matches:
        raise RuntimeError(
            f"{notebook.notebook_id}: expected {expected}, got {actual or 'unknown'}"
        )


async def verify_uploads(
    config: DemoConfig, mcp_clients: list[Client]
) -> list[dict[str, Any]]:
    results = []
    for client, notebook in zip(mcp_clients, config.notebooks, strict=True):
        runtime = await call(
            client,
            "connect_runtime",
            {"notebook_id": notebook.notebook_id},
        )
        verify_hardware(notebook, runtime)
        upload = await call(
            client,
            "upload_file",
            {
                "notebook_id": notebook.notebook_id,
                "source": str(UPLOAD_FILE),
                "destination": destination(notebook),
            },
        )
        if upload.get("state") != "complete":
            raise RuntimeError(
                f"{notebook.notebook_id}: upload did not verify as complete"
            )
        files = await call(
            client,
            "list_runtime_files",
            {
                "notebook_id": notebook.notebook_id,
                "path": str(Path(destination(notebook)).parent),
            },
        )
        sync = await call(
            client,
            "sync_notebook_to_local",
            {"notebook_id": notebook.notebook_id},
        )
        results.append(
            {
                "notebook_id": notebook.notebook_id,
                "runtime": runtime,
                "upload": upload,
                "files": files,
                "sync": sync,
            }
        )
    return results


async def _run_and_sync_one(client: Client, notebook: NotebookConfig) -> dict[str, Any]:
    """Run all code cells in one notebook, then sync to local.

    Deliberately no connect_runtime first: it executes its status probe through
    run_code, which inserts a cell that is never removed — the sync would write
    that probe cell into the local .ipynb. Running the first document cell makes
    Colab connect the runtime itself; it only bears the spin-up latency.
    """
    nid = notebook.notebook_id
    cells_payload = await call(client, "get_cells", {"notebook_id": nid})
    if isinstance(cells_payload, list):
        cells = cells_payload
    else:
        cells = cells_payload.get("cells", [])
    if not isinstance(cells, list):
        cells = []
    cell_results = []
    for cell in cells:
        if cell.get("cell_type") != "code":
            continue
        cell_id = cell.get("id") or cell.get("cellId")
        if not isinstance(cell_id, str):
            continue
        run_result = await call(
            client, "run_code_cell", {"notebook_id": nid, "cellId": cell_id}
        )
        cell_results.append({"cellId": cell_id, "result": run_result})
    sync = await call(client, "sync_notebook_to_local", {"notebook_id": nid})
    return {
        "notebook_id": nid,
        "cells_run": len(cell_results),
        "cell_results": cell_results,
        "sync": sync,
    }


async def run_and_sync(
    config: DemoConfig, mcp_clients: list[Client]
) -> list[dict[str, Any]]:
    """Run all code cells in all notebooks concurrently, then sync each to local."""
    return list(
        await asyncio.gather(
            *(
                _run_and_sync_one(client, notebook)
                for client, notebook in zip(mcp_clients, config.notebooks, strict=True)
            )
        )
    )


async def profile_login_check() -> bool:
    """Headless check of the persistent browser profile for a valid Google session.

    Returns True if already signed in; False if sign-in is needed. Does not modify
    the profile — call browser_login() if this returns False.
    """
    browser = BrowserController(headless=True)
    await browser.start()
    try:
        page = await browser.open_page(f"{COLAB}{SCRATCH_PATH}")
        for _ in range(SESSION_CHECK_POLLS):
            if await signed_in(page):
                print("Persistent browser profile: signed in.", flush=True)
                return True
            await asyncio.sleep(LOGIN_POLL_S)
        print("Persistent browser profile: not signed in.", flush=True)
        return False
    finally:
        await browser.aclose()


async def live_phase(
    config: DemoConfig,
    phase: Literal["prepare", "configure", "verify-upload", "run-notebooks"],
    auto_approve: bool = False,
    headless: bool = False,
    cdp_url: str | None = None,
    session_file: Path | None = None,
) -> None:
    os.environ[UPLOAD_DIRS_ENV] = str(UPLOAD_FILE.parent)
    os.environ[NOTEBOOK_DIRS_ENV] = os.pathsep.join(
        sorted(
            {
                str(notebook.local_path.expanduser().resolve().parent)
                for notebook in config.notebooks
            }
        )
    )
    browser = None
    if auto_approve:
        browser = BrowserController(
            headless=headless, cdp_url=cdp_url, session_file=session_file
        )
        await browser.start()
        print(
            "Managed browser started; Colab MCP dialogs will be approved automatically."
        )
    manager = SessionManager(browser=browser)
    server = build_server(manager, config.oauth_config_path)
    try:
        async with AsyncExitStack() as stack:
            mcp_clients = await clients(server, len(config.notebooks), stack)
            await register_and_open(config, mcp_clients)
            if phase == "prepare":
                statuses = await asyncio.gather(
                    *(
                        call(
                            client,
                            "get_runtime_status",
                            {"notebook_id": notebook.notebook_id},
                        )
                        for client, notebook in zip(
                            mcp_clients, config.notebooks, strict=True
                        )
                    )
                )
                print(json.dumps({"runtime_statuses": statuses}, indent=2))
                assignments(config)
                return
            if phase == "configure":
                results = await configure_runtimes(config, mcp_clients)
                print(json.dumps({"runtime_requests": results}, indent=2))
                return
            if phase == "run-notebooks":
                results = await run_and_sync(config, mcp_clients)
                print(json.dumps({"results": results}, indent=2))
                return
            results = await verify_uploads(config, mcp_clients)
            print(json.dumps({"verification": results}, indent=2))
    finally:
        await manager.aclose()
        if browser is not None:
            await browser.aclose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=COMMANDS,
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help=(
            "open notebook tabs in a managed Chromium that accepts Colab's MCP "
            "dialog automatically. The first run needs a manual Google sign-in in "
            "that window; the profile is reused afterwards."
        ),
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run the managed browser headless (only after signing in once)",
    )
    parser.add_argument(
        "--session-file",
        default=None,
        help=(
            "browser session exported with 'export-session'. Lets a headless, "
            "display-less server run signed in: Google only checks for automation "
            "at sign-in, not afterwards. Treat the file as a credential."
        ),
    )
    parser.add_argument(
        "--cdp-url",
        default=None,
        help=(
            "attach to a Chrome you started yourself (see the 'chrome' command) "
            f"instead of launching one, e.g. {CDP_URL}. Google refuses sign-in in "
            "automated browsers, so this is how a real signed-in session is used."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    if args.command == "plan":
        print(json.dumps({"notebooks": plan(config)}, indent=2))
    elif args.command == "auth":
        authenticate(config)
    elif args.command == "auth-check":
        check_auth(config)
    elif args.command == "login":
        ok = asyncio.run(browser_login())
        raise SystemExit(0 if ok else 1)
    elif args.command == "chrome":
        launch_chrome()
    elif args.command == "export-session":
        asyncio.run(
            export_session(args.cdp_url or CDP_URL, session_path(args.session_file))
        )
    elif args.command == "session-check":
        ok = asyncio.run(session_check(session_path(args.session_file)))
        raise SystemExit(0 if ok else 1)
    elif args.command == "assignments":
        assignments(config)
    elif args.command == "check-login":
        ok = asyncio.run(profile_login_check())
        raise SystemExit(0 if ok else 1)
    elif args.command == "run":

        async def _run() -> None:
            # Each credential source has its own recovery path; an interactive
            # sign-in only ever helps the persistent-profile case.
            if args.cdp_url:
                # The operator owns (and signed into) the attached Chrome; the
                # persistent profile is irrelevant, so there is nothing to check.
                pass
            elif args.session_file:
                if not await session_check(
                    session_path(args.session_file), headless=True
                ):
                    # Signing in here would refresh the profile, not this file —
                    # the run would still replay the stale session and fail.
                    raise SystemExit(
                        "The session file is expired. On a machine with a "
                        "display, re-run 'chrome', sign in, 'export-session', "
                        "and copy the file here."
                    )
            elif not await profile_login_check():
                if args.headless:
                    raise SystemExit(
                        "Not signed in, and --headless cannot open a sign-in "
                        "window. Run 'login' once with a display, or use "
                        "--session-file with a session exported elsewhere."
                    )
                print(
                    "Not logged in. Opening browser for Google sign-in...", flush=True
                )
                if not await browser_login():
                    raise SystemExit(
                        "Login was not completed. Re-run 'run' to try again."
                    )
            await live_phase(
                config,
                "run-notebooks",
                auto_approve=args.auto_approve,
                headless=args.headless,
                cdp_url=args.cdp_url,
                session_file=session_path(args.session_file)
                if args.session_file
                else None,
            )

        asyncio.run(_run())
    else:
        asyncio.run(
            live_phase(
                config,
                args.command,
                args.auto_approve,
                args.headless,
                cdp_url=args.cdp_url,
                session_file=session_path(args.session_file)
                if args.session_file
                else None,
            )
        )


if __name__ == "__main__":
    main()
