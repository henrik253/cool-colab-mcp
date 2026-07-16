import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cool_colab_mcp.constants import UPLOAD_CHUNK_SIZE, UPLOAD_DIRS_ENV
from cool_colab_mcp.errors import ToolFailed
from cool_colab_mcp.transfers import UploadManager, UploadStatus


def session(results=None):
    value = SimpleNamespace(notebook_id="nb")
    value.run_code = AsyncMock(side_effect=results)
    return value


def verification(data: bytes):
    return {
        "text": json.dumps(
            {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        )
    }


def selected(code: str, operation: str) -> bool:
    return f"_op = {operation!r}" in code


@pytest.fixture
def allowed(tmp_path, monkeypatch):
    monkeypatch.setenv(UPLOAD_DIRS_ENV, str(tmp_path))
    return tmp_path


class TestUploadFile:
    @pytest.mark.asyncio
    async def test_chunks_and_verifies_file(self, allowed):
        data = b"a" * (UPLOAD_CHUNK_SIZE + 7)
        source = allowed / "model.bin"
        source.write_bytes(data)
        runtime = session([{}, {}, {}, verification(data)])

        status = await UploadManager().upload_file(
            runtime, str(source), "artifacts/model.bin"
        )

        assert status.state == "complete"
        assert status.bytes_sent == len(data)
        assert status.destination == "/content/artifacts/model.bin"
        assert runtime.run_code.await_count == 4

    @pytest.mark.asyncio
    async def test_verification_failure_cleans_incomplete_file(self, allowed):
        source = allowed / "bad.bin"
        source.write_bytes(b"payload")
        runtime = session([{}, {}, {"size": 1, "sha256": "wrong"}, {}])

        with pytest.raises(ToolFailed) as failure:
            await UploadManager().upload_file(runtime, str(source))

        assert failure.value.error.kind == "protocol_error"
        assert selected(runtime.run_code.await_args_list[-1].args[0], "remove")

    @pytest.mark.asyncio
    async def test_transfer_failure_cleans_incomplete_file(self, allowed):
        source = allowed / "bad.bin"
        source.write_bytes(b"payload")
        runtime = session([{}, RuntimeError("drop"), {}])
        manager = UploadManager()

        with pytest.raises(ToolFailed):
            await manager.upload_file(runtime, str(source))

        status = next(iter(manager._uploads.values()))
        assert status.state == "failed"
        assert selected(runtime.run_code.await_args_list[-1].args[0], "remove")

    @pytest.mark.asyncio
    async def test_cleanup_failure_is_reported_honestly(self, allowed):
        source = allowed / "bad.bin"
        source.write_bytes(b"payload")
        runtime = session(
            [{}, RuntimeError("upload drop"), RuntimeError("cleanup drop")]
        )
        manager = UploadManager()

        with pytest.raises(ToolFailed) as failure:
            await manager.upload_file(runtime, str(source), upload_id="failed")

        assert failure.value.error.kind == "protocol_error"
        assert "could not be confirmed" in failure.value.error.message
        assert failure.value.error.details == {
            "notebook_id": "nb",
            "destination": "/content/bad.bin",
        }
        assert "manually" in manager.status("failed").error

    @pytest.mark.asyncio
    async def test_cancelled_upload_is_cleaned(self, allowed):
        source = allowed / "large.bin"
        source.write_bytes(b"a" * (UPLOAD_CHUNK_SIZE + 1))
        manager = UploadManager()
        first_chunk = asyncio.Event()

        async def execute(code):
            if selected(code, "append"):
                first_chunk.set()
                await asyncio.sleep(0)
            return {}

        runtime = session()
        runtime.run_code.side_effect = execute
        task = asyncio.create_task(
            manager.upload_file(runtime, str(source), upload_id="known-id")
        )
        await first_chunk.wait()
        manager.cancel("known-id")

        with pytest.raises(ToolFailed):
            await task
        assert manager.status("known-id").state == "cancelled"
        remove_calls = [
            call
            for call in runtime.run_code.await_args_list
            if selected(call.args[0], "remove")
        ]
        assert len(remove_calls) == 1

    @pytest.mark.asyncio
    async def test_duplicate_caller_supplied_upload_id_rejected(self, allowed):
        source = allowed / "file"
        source.write_bytes(b"x")
        manager = UploadManager()
        manager._uploads["same"] = UploadStatus(
            upload_id="same",
            notebook_id="nb",
            source="x",
            destination="/content/x",
            state="complete",
            bytes_sent=1,
            size=1,
            sha256="x",
        )
        with pytest.raises(ToolFailed) as failure:
            await manager.upload_file(session(), str(source), upload_id="same")
        assert failure.value.error.kind == "invalid_input"

    @pytest.mark.asyncio
    async def test_empty_caller_supplied_upload_id_rejected(self, allowed):
        source = allowed / "file"
        source.write_bytes(b"x")
        with pytest.raises(ToolFailed) as failure:
            await UploadManager().upload_file(session(), str(source), upload_id=" ")
        assert failure.value.error.kind == "invalid_input"

    @pytest.mark.asyncio
    async def test_concurrent_destination_collision_is_rejected(self, allowed):
        source = allowed / "file"
        source.write_bytes(b"x")
        manager = UploadManager()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked_init(code):
            if selected(code, "init"):
                entered.set()
                await release.wait()
            return verification(b"x") if selected(code, "verify") else {}

        first_runtime = session()
        first_runtime.run_code.side_effect = blocked_init
        first = asyncio.create_task(
            manager.upload_file(first_runtime, str(source), upload_id="first")
        )
        await entered.wait()

        with pytest.raises(ToolFailed) as failure:
            await manager.upload_file(session(), str(source), upload_id="second")
        assert failure.value.error.kind == "invalid_input"
        assert failure.value.error.details["destination"] == "/content/file"
        release.set()
        assert (await first).state == "complete"


class TestPathRestrictions:
    @pytest.mark.asyncio
    async def test_uploads_disabled_without_configuration(self, tmp_path, monkeypatch):
        monkeypatch.delenv(UPLOAD_DIRS_ENV, raising=False)
        source = tmp_path / "file"
        source.write_text("x")
        with pytest.raises(ToolFailed) as failure:
            await UploadManager().upload_file(session(), str(source))
        assert failure.value.error.kind == "user_action_required"

    @pytest.mark.asyncio
    async def test_source_outside_allowed_root_rejected(
        self, allowed, tmp_path_factory
    ):
        source = tmp_path_factory.mktemp("outside") / "file"
        source.write_text("x")
        with pytest.raises(ToolFailed) as failure:
            await UploadManager().upload_file(session(), str(source))
        assert failure.value.error.kind == "invalid_input"

    @pytest.mark.asyncio
    async def test_destination_outside_content_rejected(self, allowed):
        source = allowed / "file"
        source.write_text("x")
        with pytest.raises(ToolFailed) as failure:
            await UploadManager().upload_file(session(), str(source), "/tmp/file")
        assert failure.value.error.kind == "invalid_input"


class TestUploadDirectory:
    @pytest.mark.asyncio
    async def test_recurses_and_preserves_relative_paths(self, allowed):
        root = allowed / "dataset"
        (root / "nested").mkdir(parents=True)
        (root / "a.txt").write_bytes(b"a")
        (root / "nested" / "b.txt").write_bytes(b"bb")
        runtime = session([{}, {}, verification(b"a"), {}, {}, verification(b"bb")])

        statuses = await UploadManager().upload_directory(runtime, str(root), "data")

        assert [item.destination for item in statuses] == [
            "/content/data/a.txt",
            "/content/data/nested/b.txt",
        ]


class TestRuntimeFiles:
    @pytest.mark.asyncio
    async def test_lists_runtime_files(self):
        files = [{"path": "/content/a", "size": 3}]
        runtime = session([{"text": json.dumps({"files": files})}])
        assert await UploadManager().list_runtime_files(runtime) == files

    @pytest.mark.asyncio
    async def test_invalid_runtime_response_is_structured(self):
        with pytest.raises(ToolFailed) as failure:
            await UploadManager().list_runtime_files(session([{}]))
        assert failure.value.error.kind == "protocol_error"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("operation", ["upload", "remove", "list"])
    async def test_runtime_resolved_path_escape_is_invalid_input(
        self, allowed, operation
    ):
        source = allowed / "file"
        source.write_bytes(b"x")
        runtime_error = {
            "error": {
                "kind": "invalid_input",
                "message": "Runtime path escapes /content.",
            }
        }
        manager = UploadManager()
        runtime = session([runtime_error])

        with pytest.raises(ToolFailed) as failure:
            if operation == "list":
                await manager.list_runtime_files(runtime, "/content/link")
            elif operation == "remove":
                await manager._run(runtime, "remove", path="/content/link/file")
            else:
                await manager.upload_file(runtime, str(source), "/content/link/file")

        assert failure.value.error.kind == "invalid_input"
        assert runtime.run_code.await_count == 1
        if operation != "remove":
            assert not any(
                selected(call.args[0], "remove")
                for call in runtime.run_code.await_args_list
            )

    def test_runtime_code_resolves_paths_beneath_content(self):
        from cool_colab_mcp.transfers import _code

        code = _code("list", path="/content/link")
        assert "os.path.realpath" in code
        assert "os.path.commonpath" in code


class TestStatus:
    def test_unknown_upload_id_rejected(self):
        with pytest.raises(ToolFailed) as failure:
            UploadManager().status("missing")
        assert failure.value.error.kind == "invalid_input"
