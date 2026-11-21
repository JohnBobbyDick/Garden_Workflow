import csv
import io

from tests.api.conftest import drain
from tests.api.test_api_core import create_wf
from tests.engine.helpers import graph
from tests.nodes.conftest import TRAINING

REVIEW_NODES = [
    ("paths", "logic.path_filter", {"include": ["**/*.kt"]}),
    ("delta", "logic.finding_delta", {}),
    ("sample", "analysis.audit_sample", {"size": 2}),
    ("hotspots", "analysis.file_hotspots", {}),
    ("updates", "analysis.dependency_fixes", {}),
    ("budget", "analysis.severity_budget", {}),
    ("fields", "logic.check_fields", {"paths": ["within_budget", "total_files"]}),
    ("join", "logic.join_json", {}),
    ("message", "logic.render_text", {"template": "{{data.valid}}"}),
    ("csv", "output.findings_csv", {}),
]


def test_catalog_types_validate_and_execute_in_worker(client, db, alice, bob):
    catalog = {n["type"]: n for n in client.get("/api/nodes", headers=alice.headers).json()["nodes"]}
    for _, node_type, _ in REVIEW_NODES:
        assert all(catalog[node_type]["title"].get(lang) and catalog[node_type]["description"].get(lang)
                   for lang in ["ru", "en"])
    nodes = [("t", "trigger.manual", {}), ("repo", "source.repo", {"mode": "path", "path": str(TRAINING)}),
             ("sec", "scanner.secrets", {}), ("sca", "scanner.sca", {}), ("merged", "logic.merge", {}),
             *REVIEW_NODES, ("full_csv", "output.findings_csv", {})]
    edges = [
        ("t", "out", "repo", "in"), ("repo", "out", "sec", "in"), ("repo", "out", "sca", "in"),
        ("sec", "out", "merged", "in"), ("sca", "out", "merged", "in"),
        ("merged", "out", "paths", "in"), ("merged", "out", "delta", "current"), ("paths", "out", "delta", "baseline"),
        ("delta", "added", "hotspots", "in"), ("merged", "out", "sample", "in"), ("sample", "out", "csv", "in"),
        ("merged", "out", "full_csv", "in"), ("sca", "out", "updates", "in"), ("merged", "out", "budget", "in"),
        ("hotspots", "out", "join", "left"), ("budget", "out", "join", "right"),
        ("join", "out", "fields", "in"), ("fields", "out", "message", "in"),
    ]
    wid = create_wf(client, alice, graph(nodes, edges))
    valid = client.post(f"/api/workflows/{wid}/validate", headers=alice.headers).json()
    assert valid["valid"], valid
    start = client.post(f"/api/workflows/{wid}/run", headers=alice.headers)
    assert start.status_code == 202, start.text
    rid = start.json()["id"]
    assert drain(db) == [rid]
    run = client.get(f"/api/runs/{rid}", headers=alice.headers).json()
    assert run["status"] == "success"
    assert {n["node_id"] for n in run["nodes"] if n["status"] == "success"} == {n[0] for n in nodes}
    csv_rows = {}
    for artifact in run["artifacts"]:
        response = client.get(artifact["url"], headers=alice.headers)
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
        assert client.get(artifact["url"], headers=bob.headers).status_code == 404
        csv_rows[artifact["node_id"]] = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert len(csv_rows["csv"]) == 2 < len(csv_rows["full_csv"]) == run["summary"]["total"]
    assert all(row in csv_rows["full_csv"] for row in csv_rows["csv"])
