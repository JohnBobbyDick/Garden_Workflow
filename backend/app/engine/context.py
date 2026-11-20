"""Execution context handed to every node."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from app.core.masking import Masker

if TYPE_CHECKING:
    from app.analyzers.common.finding import Finding


class EventSink(Protocol):
    def emit(self, type_: str, node_id: str | None, data: dict[str, Any]) -> None: ...


class RunServices(Protocol):
    """Platform services available to nodes during a run (implemented by the DB-backed worker services)."""

    def get_credential(self, credential_id: str) -> str: ...

    def workdir(self) -> Path: ...

    def save_artifact(self, node_id: str, name: str, content: bytes, content_type: str) -> str: ...

    def record_findings(self, node_id: str, findings: list[Finding]) -> None: ...

    def update_run(self, **fields: Any) -> None: ...

    def add_notification(self, node_id: str, channel: str, status: str, detail: str = "") -> None: ...

    def allowlist(self) -> list[str]: ...

    def open_upload(self, upload_id: str) -> tuple[str, bytes]: ...

    def project_source(self) -> dict[str, Any] | None: ...

    def workspace_settings(self) -> dict[str, Any]: ...


@dataclass
class RunInfo:
    run_id: str
    workspace_id: str
    workflow_id: str | None = None
    project_id: str | None = None
    trigger_type: str = "manual"
    trigger_node_id: str | None = None
    trigger_payload: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)
    triggered_by: str | None = None
    language: str = "ru"
    public_url: str = ""
    project_name: str = ""
    workflow_name: str = ""

    @property
    def run_url(self) -> str:
        return f"{self.public_url.rstrip('/')}/runs/{self.run_id}" if self.public_url else f"/runs/{self.run_id}"


class NodeContext:
    def __init__(self, run: RunInfo, node_id: str, node_type: str, sink: EventSink, masker: Masker,
                 services: RunServices | None, state: dict[str, Any]) -> None:
        self.run = run
        self.node_id = node_id
        self.node_type = node_type
        self._sink = sink
        self.masker = masker
        self._services = services
        self.state = state  # shared across nodes of one run

    @property
    def services(self) -> RunServices:
        if self._services is None:
            raise RuntimeError("platform services are not available in this execution context")
        return self._services

    @property
    def has_services(self) -> bool:
        return self._services is not None

    def log(self, level: str, message: str) -> None:
        self._sink.emit("node.log", self.node_id, {"level": level, "message": self.masker.mask(str(message))[:4000]})

    def secret(self, credential_id: str) -> str:
        """Decrypt a credential and register it for masking everywhere in this run."""
        value = self.services.get_credential(credential_id)
        self.masker.register(value)
        return value
