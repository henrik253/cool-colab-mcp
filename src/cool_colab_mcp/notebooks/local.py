"""Restricted access to registered local repository notebooks."""

import os
from pathlib import Path

from cool_colab_mcp.constants import NOTEBOOK_DIRS_ENV, NOTEBOOK_SUFFIX
from cool_colab_mcp.errors import fail
from cool_colab_mcp.snapshots.manager import load_notebook, write_notebook


def allowed_notebook_roots() -> tuple[Path, ...]:
    value = os.environ.get(NOTEBOOK_DIRS_ENV, "")
    return tuple(
        Path(item).expanduser().resolve() for item in value.split(os.pathsep) if item
    )


def local_notebook_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    roots = allowed_notebook_roots()
    if not roots:
        raise fail(
            "user_action_required",
            f"Local notebook sync is disabled — configure {NOTEBOOK_DIRS_ENV} first.",
        )
    if not any(path == root or path.is_relative_to(root) for root in roots):
        raise fail(
            "invalid_input",
            "Notebook path is outside the configured notebook directories.",
            path=str(path),
        )
    if path.suffix != NOTEBOOK_SUFFIX:
        raise fail(
            "invalid_input", f"Local notebook path must end with {NOTEBOOK_SUFFIX}."
        )
    return path


def read_local_notebook(value: str) -> dict:
    return load_notebook(local_notebook_path(value))


def write_local_notebook(value: str, document: dict) -> Path:
    path = local_notebook_path(value)
    try:
        write_notebook(path, document)
    except OSError as exc:
        raise fail("invalid_input", f"Cannot write local notebook '{path}'.") from exc
    return path
