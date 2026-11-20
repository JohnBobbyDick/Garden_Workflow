"""`make test-eval`: recall/precision on the organizer training set and on our mutants.

Fails on any missed expected finding, any hit on a safe control, or any unexplained extra finding.
"""

from pathlib import Path

import pytest

from app.analyzers.runner import analyze_project
from tests.eval.harness import evaluate

pytestmark = pytest.mark.eval

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
TRAINING = FIXTURES / "organizer-training"
MUTANTS = sorted(p for p in (FIXTURES / "mutants").glob("*") if (p / "expected.json").is_file())


def _check(project: Path, expected: Path, name: str):
    result = analyze_project(project)
    rep = evaluate(result.findings, expected, name)
    print("\n" + rep.summary())
    assert not rep.missed, rep.summary()
    assert not rep.control_hits, rep.summary()
    assert not rep.extras, rep.summary()


def test_training_set():
    _check(TRAINING / "training-project", TRAINING / "ground-truth" / "training-findings.json", "training")


@pytest.mark.parametrize("mutant", MUTANTS, ids=[m.name for m in MUTANTS])
def test_mutant(mutant: Path):
    _check(mutant / "project", mutant / "expected.json", mutant.name)
