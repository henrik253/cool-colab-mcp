# Copyright 2026 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""NotebookRecord and its persistent store on top of storage.py (plan.md §4)."""

from pydantic import BaseModel, ValidationError, field_validator

from cool_colab_mcp import storage
from cool_colab_mcp.constants import DEFAULT_NOTEBOOK_ID, REGISTRY_STORE
from cool_colab_mcp.errors import fail
from cool_colab_mcp.sessions.session import validate_notebook_url


class NotebookRecord(BaseModel):
    """One registered notebook: a human-chosen id mapped to its Colab URL."""

    notebook_id: str  # the registry key, a human-chosen slug
    name: str
    url: str
    preferred_runtime: str | None = None  # e.g. "cpu"/"gpu"; stored for the
    # future change_runtime feature (plan.md §8) — no behavior yet

    @field_validator("notebook_id")
    @classmethod
    def _usable_notebook_id(cls, notebook_id: str) -> str:
        if not notebook_id:
            raise fail("invalid_input", "notebook_id must be a non-empty slug.")
        if notebook_id == DEFAULT_NOTEBOOK_ID:
            raise fail(
                "invalid_input",
                f"notebook_id '{DEFAULT_NOTEBOOK_ID}' is reserved for the anonymous "
                "default session — pick another slug.",
            )
        return notebook_id

    @field_validator("url")
    @classmethod
    def _colab_notebook_url(cls, url: str) -> str:
        return validate_notebook_url(url)


class NotebookRegistry:
    """The persistent notebook_id → NotebookRecord map.

    Every operation reads/writes the atomic JSON store, so records survive
    server restarts and no in-memory state can go stale.
    """

    def list(self) -> list[NotebookRecord]:
        """All registered records."""
        return list(self._records().values())

    def get(self, notebook_id: str) -> NotebookRecord:
        """The record for notebook_id; raises a structured error if unregistered."""
        record = self._records().get(notebook_id)
        if record is None:
            raise fail(
                "unknown_notebook",
                f"No registered notebook '{notebook_id}' — "
                "register it first with register_notebook.",
                notebook_id=notebook_id,
            )
        return record

    def register(self, record: NotebookRecord) -> None:
        """Add the record, replacing any existing record with the same id."""
        with storage.lock(REGISTRY_STORE):
            records = self._records()
            records[record.notebook_id] = record
            self._save(records)

    def remove(self, notebook_id: str) -> None:
        """Delete the record for notebook_id; raises a structured error if unregistered."""
        with storage.lock(REGISTRY_STORE):
            records = self._records()
            if notebook_id not in records:
                raise fail(
                    "unknown_notebook",
                    f"No registered notebook '{notebook_id}' — nothing to remove.",
                    notebook_id=notebook_id,
                )
            del records[notebook_id]
            self._save(records)

    def _records(self) -> dict[str, NotebookRecord]:
        try:
            return {
                notebook_id: NotebookRecord.model_validate(data)
                for notebook_id, data in storage.load(REGISTRY_STORE).items()
            }
        except (AttributeError, ValueError, ValidationError) as exc:
            raise fail(
                "protocol_error",
                f"The notebook registry store is corrupted — fix or delete the "
                f"'{REGISTRY_STORE}' file in the state directory.",
            ) from exc

    def _save(self, records: dict[str, NotebookRecord]) -> None:
        storage.save(
            REGISTRY_STORE,
            {
                notebook_id: record.model_dump(exclude_none=True)
                for notebook_id, record in records.items()
            },
        )
