"""A whole repository (link / path / GitHub «Download ZIP») is scanned from its Gradle project root, so finding paths
match the organizers' format and SCA sees build.gradle.kts."""

import io
import zipfile

from tests.api.conftest import drain
from tests.engine.test_worker_scheduler import full_graph
from tests.nodes.conftest import TRAINING

REPO = TRAINING.parent  # fixtures/organizer-training: README, docs, ground-truth, training-project, …


def run_with_source(client, db, user, source: dict) -> dict:
    g = full_graph()
    g["nodes"][1]["config"] = source
    wid = client.post("/api/workflows", json={"name": "root", "graph": g, "workspace_id": user.workspace_id},
                      headers=user.headers).json()["id"]
    rid = client.post(f"/api/workflows/{wid}/run", headers=user.headers).json()["id"]
    drain(db)
    return client.get(f"/api/runs/{rid}", headers=user.headers).json()


def findings(client, user, rid):
    return client.get(f"/api/runs/{rid}/findings", headers=user.headers).json()["findings"]


def assert_project_relative(fs):
    assert len(fs) == 15, [f["path"] for f in fs]
    assert not [f["path"] for f in fs if f["path"].startswith("training-project/")]
    assert sum(1 for f in fs if f["category"] == "SCA") == 5
    assert "src/main/kotlin/lab/repairdesk/integration/DepotStatusClient.kt" in {f["path"] for f in fs}


def test_repository_root_path_scans_detected_project(client, db, alice):
    run = run_with_source(client, db, alice, {"mode": "path", "path": str(REPO)})
    assert run["status"] == "success", run["error"]
    assert run["source"]["subdir"] == "training-project" and run["source"]["subdir_detected"] is True
    assert_project_relative(findings(client, alice, run["id"]))
    exported = client.get(f"/api/runs/{run['id']}/export/submission.json", headers=alice.headers).json()["findings"]
    assert exported and all(not f["path"].startswith("training-project/") for f in exported)
    logs = [n for n in run["nodes"] if n["node_id"] == "src"][0]
    assert logs["status"] == "success"


def test_github_download_zip_is_scanned_from_project_root(client, db, alice):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in REPO.rglob("*"):
            if p.is_file():
                z.write(p, f"training-main/{p.relative_to(REPO).as_posix()}")
    up = client.post("/api/uploads", data={"workspace_id": alice.workspace_id},
                     files={"file": ("training-main.zip", buf.getvalue(), "application/zip")}, headers=alice.headers)
    assert up.status_code == 201, up.text
    run = run_with_source(client, db, alice, {"mode": "upload", "upload_id": up.json()["id"]})
    assert run["status"] == "success", run["error"]
    assert run["source"]["subdir"] == "training-project"
    assert_project_relative(findings(client, alice, run["id"]))


def test_explicit_subdir_is_respected_and_not_overridden(client, db, alice):
    run = run_with_source(client, db, alice, {"mode": "path", "path": str(REPO), "subdir": "training-project"})
    assert run["source"]["subdir"] == "training-project" and not run["source"].get("subdir_detected")
    assert_project_relative(findings(client, alice, run["id"]))


def test_autofix_works_on_a_detected_root(client, db, alice):
    run = run_with_source(client, db, alice, {"mode": "path", "path": str(REPO)})
    sca = next(f for f in findings(client, alice, run["id"]) if f["category"] == "SCA" and f["autofix"] == "deterministic")
    af = client.post(f"/api/runs/{run['id']}/findings/{sca['id']}/autofix", headers=alice.headers).json()
    assert af["status"] == "validated", af
    patch = client.get(f"/api/autofixes/{af['id']}/patch", headers=alice.headers).text
    assert "a/build.gradle.kts" in patch and "training-project/" not in patch
