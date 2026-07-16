"""Live three-notebook demo for registry, auth, runtime control, and uploads."""

import argparse
import asyncio
import json
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Literal

from fastmcp import Client
from pydantic import BaseModel, field_validator, model_validator

from cool_colab_mcp.auth import ensure_credentials, run_consent_flow
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
    RUNTIME_DIR,
    RUNTIME_PROFILES,
    UPLOAD_DIRS_ENV,
    UPLOAD_FILENAME,
)
from cool_colab_mcp.runtime.client import RuntimeClient
from cool_colab_mcp.server import build_server
from cool_colab_mcp.sessions.manager import SessionManager

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
    def exactly_three_distinct_notebooks(self) -> "DemoConfig":
        if len(self.notebooks) != NOTEBOOK_COUNT:
            raise ValueError("the demo requires exactly three notebooks")
        ids = [notebook.notebook_id for notebook in self.notebooks]
        if len(set(ids)) != len(ids):
            raise ValueError("notebook_id values must be unique")
        profiles = [notebook.runtime_profile for notebook in self.notebooks]
        if (
            profiles.count(CPU_PROFILE) != CPU_COUNT
            or profiles.count(GPU_PROFILE) != GPU_COUNT
        ):
            raise ValueError("the demo requires two prototype-cpu and one debug-gpu")
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
    await asyncio.gather(
        *(
            call(client, "open_notebook", {"notebook_id": notebook.notebook_id})
            for client, notebook in zip(mcp_clients, config.notebooks, strict=True)
        )
    )


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


async def live_phase(
    config: DemoConfig, phase: Literal["prepare", "configure", "verify-upload"]
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
    manager = SessionManager()
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
            results = await verify_uploads(config, mcp_clients)
            print(json.dumps({"verification": results}, indent=2))
    finally:
        await manager.aclose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=COMMANDS,
    )
    parser.add_argument("--config", type=Path, required=True)
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
    elif args.command == "assignments":
        assignments(config)
    else:
        asyncio.run(live_phase(config, args.command))


if __name__ == "__main__":
    main()
