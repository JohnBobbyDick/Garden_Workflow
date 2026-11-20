import asyncio
import shutil
from pathlib import Path

import pytest

from app.config import REPO_ROOT
from app.core.masking import Masker
from app.engine.context import NodeContext, RunInfo
from app.engine.executor import ListSink, apply_defaults
from app.nodes.base import get_registry

TRAINING = REPO_ROOT / "fixtures" / "organizer-training" / "training-project"


class StubServices:
    """Test double of RunServices: keeps everything in memory."""

    def __init__(self, tmp: Path, credentials: dict[str, str] | None = None, allowlist=None):
        self.tmp = tmp
        self.credentials = credentials or {}
        self.artifacts: dict[str, tuple[bytes, str]] = {}
        self.findings: list = []
        self.run_fields: dict = {}
        self.notifications: list = []
        self.allow = allowlist or ["https://github.com/TBagirov/training"]
        self.uploads: dict[str, tuple[str, bytes]] = {}
        self.project: dict | None = None
        self.settings: dict = {}

    def get_credential(self, cid):
        if cid not in self.credentials:
            raise KeyError(cid)
        return self.credentials[cid]

    def workdir(self):
        d = self.tmp / "work"
        d.mkdir(exist_ok=True)
        return d

    def save_artifact(self, node_id, name, content, content_type):
        self.artifacts[name] = (content, content_type)
        return f"/api/runs/r1/artifacts/{name}"

    def record_findings(self, node_id, findings):
        self.findings.extend(findings)

    def update_run(self, **fields):
        self.run_fields.update(fields)

    def add_notification(self, node_id, channel, status, detail=""):
        self.notifications.append({"node_id": node_id, "channel": channel, "status": status, "detail": detail})

    def allowlist(self):
        return self.allow

    def open_upload(self, upload_id):
        return self.uploads[upload_id]

    def project_source(self):
        return self.project

    def workspace_settings(self):
        return self.settings


@pytest.fixture
def services(tmp_path):
    return StubServices(tmp_path)


def run_node(node_type: str, inputs: dict, config: dict, services=None, run: RunInfo | None = None,
             masker: Masker | None = None):
    cls = get_registry().get(node_type)
    assert cls is not None, node_type
    sink = ListSink()
    ctx = NodeContext(run or RunInfo(run_id="r1", workspace_id="w1", public_url="http://ui"), "n1", node_type, sink,
                      masker or Masker(), services, {})
    out = asyncio.run(cls().execute(ctx, inputs, apply_defaults(cls.config_schema, config)))
    return out, sink


@pytest.fixture
def training_copy(tmp_path):
    dst = tmp_path / "training"
    shutil.copytree(TRAINING, dst)
    return dst
