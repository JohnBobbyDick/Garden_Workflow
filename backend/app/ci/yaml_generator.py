"""GitHub Actions / GitLab CI pipeline generator. Fetch depth 0 gives the CLI the history for diff-aware scans."""

from __future__ import annotations

import yaml


def github_actions(workflow_id: str, branches: list[str] | None = None) -> str:
    br = branches or ["main"]
    doc = {
        "name": "AI Security Workflow",
        "on": {"push": {"branches": br}, "pull_request": {"branches": br}},
        "permissions": {"contents": "read", "pull-requests": "write", "statuses": "write"},
        "jobs": {"aisw": {
            "name": "aisw",
            "runs-on": "ubuntu-latest",
            "steps": [
                {"uses": "actions/checkout@v4", "with": {"fetch-depth": 0}},
                {"uses": "actions/setup-python@v5", "with": {"python-version": "3.12"}},
                {"name": "Download AISW CLI", "env": {"AISW_URL": "${{ vars.AISW_URL }}"},
                 "run": 'curl -fsSL "$AISW_URL/api/ci/cli" -o aisw_ci.py'},
                {"name": "Security scan (fails the job on Critical)",
                 "env": {"AISW_URL": "${{ vars.AISW_URL }}", "AISW_TOKEN": "${{ secrets.AISW_TOKEN }}",
                         "GITHUB_TOKEN": "${{ secrets.GITHUB_TOKEN }}"},
                 "run": (f'python aisw_ci.py --url "$AISW_URL" --workflow {workflow_id} --out aisw-report '
                         '--summary "$GITHUB_STEP_SUMMARY"')},
                {"name": "Upload report", "if": "always()", "uses": "actions/upload-artifact@v4",
                 "with": {"name": "aisw-report", "path": "aisw-report/"}},
            ]}},
    }
    header = ("# AI Security Workflow — GitHub Actions\n"
              "# 1) Settings → Secrets and variables → Actions: secret AISW_TOKEN (API-токен платформы),\n"
              "#    variable AISW_URL (адрес платформы).\n"
              "# 2) Чтобы проблемный код не попал в основную ветку: Settings → Branches → Branch protection rule →\n"
              "#    «Require status checks to pass before merging» → отметьте проверку «aisw».\n")
    return header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


def gitlab_ci(workflow_id: str) -> str:
    doc = {
        "stages": ["security"],
        "aisw_security": {
            "stage": "security",
            "image": "python:3.12-slim",
            "variables": {"GIT_DEPTH": 0},
            "rules": [{"if": '$CI_PIPELINE_SOURCE == "merge_request_event"'}, {"if": '$CI_PIPELINE_SOURCE == "push"'}],
            "script": [
                "python -c \"import os,urllib.request;urllib.request.urlretrieve(os.environ['AISW_URL']+'/api/ci/cli',"
                "'aisw_ci.py')\"",
                f'python aisw_ci.py --url "$AISW_URL" --workflow {workflow_id} --out aisw-report',
            ],
            "artifacts": {"when": "always", "paths": ["aisw-report/report.md", "aisw-report/submission.json"]},
            "allow_failure": False,
        },
    }
    header = ("# AI Security Workflow — GitLab CI\n"
              "# Settings → CI/CD → Variables: AISW_URL, AISW_TOKEN (masked). Для комментариев в MR — GITLAB_TOKEN.\n"
              "# Settings → Merge requests → «Pipelines must succeed», чтобы MR с Critical нельзя было слить.\n")
    return header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
