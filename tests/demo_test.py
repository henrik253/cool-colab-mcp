"""Tests for the three-notebook demo's user-facing plan command."""

import asyncio
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

RUNNER = Path(__file__).parents[1] / "demo" / "three_notebooks" / "run_demo.py"
SPEC = importlib.util.spec_from_file_location("three_notebook_demo", RUNNER)
assert SPEC and SPEC.loader
DEMO = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DEMO
SPEC.loader.exec_module(DEMO)


def notebook(notebook_id: str, profile: str, index: int) -> dict:
    return {
        "notebook_id": notebook_id,
        "name": notebook_id,
        "url": f"https://colab.research.google.com/drive/file-{index}",
        "runtime_profile": profile,
        "assignment_endpoint": f"endpoint-{index}",
    }


def config(**overrides) -> dict:
    fields = {
        "oauth_config_path": "/tmp/oauth.json",
        "notebooks": [
            notebook("cpu-a", "prototype-cpu", 1),
            notebook("cpu-b", "prototype-cpu", 2),
            notebook("gpu", "debug-gpu", 3),
        ],
    }
    fields.update(overrides)
    return fields


def run_plan(tmp_path: Path, data: dict) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    return subprocess.run(
        [sys.executable, str(RUNNER), "plan", "--config", str(path)],
        capture_output=True,
        check=False,
        text=True,
    )


def test_plan_has_two_cpu_one_t4_and_isolated_upload_destinations(tmp_path):
    result = run_plan(tmp_path, config())
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    notebooks = payload["notebooks"]
    assert [item["runtime_profile"] for item in notebooks] == [
        "prototype-cpu",
        "prototype-cpu",
        "debug-gpu",
    ]
    assert len({item["upload_destination"] for item in notebooks}) == 3


def test_plan_requires_three_unique_notebooks(tmp_path):
    duplicate = notebook("same", "prototype-cpu", 1)
    result = run_plan(
        tmp_path,
        config(notebooks=[duplicate, duplicate, notebook("gpu", "debug-gpu", 3)]),
    )
    assert result.returncode != 0
    assert "notebook_id values must be unique" in result.stderr


def test_plan_requires_two_cpu_and_one_t4(tmp_path):
    result = run_plan(
        tmp_path,
        config(
            notebooks=[
                notebook("a", "debug-gpu", 1),
                notebook("b", "debug-gpu", 2),
                notebook("c", "debug-gpu", 3),
            ]
        ),
    )
    assert result.returncode != 0
    assert "two prototype-cpu and one debug-gpu" in result.stderr


def test_plan_rejects_placeholder_url(tmp_path):
    records = config()["notebooks"]
    records[0]["url"] = "https://colab.research.google.com/drive/REPLACE_WITH_FILE_ID"
    result = run_plan(tmp_path, config(notebooks=records))
    assert result.returncode != 0
    assert "replace the example Colab URL" in result.stderr


def demo_config(endpoints: bool = True):
    records = config()["notebooks"]
    if not endpoints:
        records[0]["assignment_endpoint"] = None
    return DEMO.DemoConfig.model_validate(config(notebooks=records))


@pytest.mark.asyncio
async def test_register_and_open_routes_three_notebooks_concurrently(monkeypatch):
    opened: list[str] = []
    all_open = asyncio.Event()

    async def fake_call(client, tool, arguments):
        if tool == "open_notebook":
            opened.append(arguments["notebook_id"])
            if len(opened) == 3:
                all_open.set()
            await asyncio.wait_for(all_open.wait(), timeout=1)
        return {}

    monkeypatch.setattr(DEMO, "call", fake_call)
    await DEMO.register_and_open(demo_config(), [object(), object(), object()])
    assert set(opened) == {"cpu-a", "cpu-b", "gpu"}


@pytest.mark.asyncio
async def test_configure_requires_every_assignment_endpoint():
    with pytest.raises(RuntimeError, match="cpu-a"):
        await DEMO.configure_runtimes(
            demo_config(endpoints=False), [object(), object(), object()]
        )


@pytest.mark.asyncio
async def test_configure_routes_explicit_endpoints_and_profiles(monkeypatch):
    requests = []

    async def fake_call(client, tool, arguments):
        requests.append((tool, arguments))
        return {"requested_profile": arguments["profile"]}

    monkeypatch.setattr(DEMO, "call", fake_call)
    await DEMO.configure_runtimes(demo_config(), [object(), object(), object()])
    assert [request[1]["assignment_endpoint"] for request in requests] == [
        "endpoint-1",
        "endpoint-2",
        "endpoint-3",
    ]
    assert [request[1]["profile"] for request in requests] == [
        "prototype-cpu",
        "prototype-cpu",
        "debug-gpu",
    ]


@pytest.mark.asyncio
async def test_verify_upload_accepts_two_cpu_and_one_t4(monkeypatch):
    async def fake_call(client, tool, arguments):
        notebook_id = arguments["notebook_id"]
        if tool == "connect_runtime":
            accelerator = "Tesla T4" if notebook_id == "gpu" else "CPU"
            return {"runtime": json.dumps({"accelerator": accelerator})}
        if tool == "upload_file":
            return {"state": "complete", "sha256": "verified"}
        return {"files": [{"path": arguments["path"] + "/test-upload.txt"}]}

    monkeypatch.setattr(DEMO, "call", fake_call)
    result = await DEMO.verify_uploads(demo_config(), [object(), object(), object()])
    assert [item["notebook_id"] for item in result] == ["cpu-a", "cpu-b", "gpu"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "notebook_id,actual",
    [("cpu-a", "Tesla T4"), ("gpu", "CPU")],
)
async def test_verify_upload_rejects_wrong_hardware(monkeypatch, notebook_id, actual):
    async def fake_call(client, tool, arguments):
        if tool == "connect_runtime":
            accelerator = actual if arguments["notebook_id"] == notebook_id else "CPU"
            return {"runtime": {"accelerator": accelerator}}
        return {"state": "complete"}

    monkeypatch.setattr(DEMO, "call", fake_call)
    with pytest.raises(RuntimeError, match="expected"):
        await DEMO.verify_uploads(demo_config(), [object(), object(), object()])


@pytest.mark.asyncio
async def test_verify_upload_rejects_unverified_upload(monkeypatch):
    async def fake_call(client, tool, arguments):
        if tool == "connect_runtime":
            accelerator = "Tesla T4" if arguments["notebook_id"] == "gpu" else "CPU"
            return {"runtime": {"accelerator": accelerator}}
        if tool == "upload_file":
            return {"state": "failed"}
        return {}

    monkeypatch.setattr(DEMO, "call", fake_call)
    with pytest.raises(RuntimeError, match="upload did not verify"):
        await DEMO.verify_uploads(demo_config(), [object(), object(), object()])


@pytest.mark.asyncio
async def test_structured_tool_failure_stops_demo_safely():
    client = SimpleNamespace(
        call_tool=AsyncMock(
            return_value=SimpleNamespace(
                structured_content={
                    "error": {
                        "kind": "user_action_required",
                        "message": "T4 quota unavailable",
                    }
                }
            )
        )
    )
    with pytest.raises(
        RuntimeError, match="user_action_required: T4 quota unavailable"
    ):
        await DEMO.call(client, "request_runtime_profile", {})
