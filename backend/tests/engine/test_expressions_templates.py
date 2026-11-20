import pytest

from app.engine.expressions import ExpressionError, evaluate, parse
from app.engine.templating import render_template

CTX = {
    "findings": {"count": 7},
    "severity": {"max": "HIGH", "critical": 0, "high": 2},
    "categories": ["SECRET", "SCA"],
    "category": ["SECRET", "SCA"],
    "new_findings": {"count": 1},
    "verdict": "FAIL",
    "score": {"value": 41, "delta": -3},
}


@pytest.mark.parametrize("expr,expected", [
    ("findings.count > 0", True),
    ("findings.count >= 8", False),
    ("severity.max >= HIGH", True),
    ("severity.max >= CRITICAL", False),
    ("severity.max == 'HIGH'", True),
    ("severity.max > MEDIUM and findings.count < 10", True),
    ("severity.max == CRITICAL or new_findings.count > 0", True),
    ("not (score.value > 50)", True),
    ("score.delta < 0", True),
    ("category == 'SECRET'", True),
    ("category == \"SAST\"", False),
    ("'SCA' in categories", True),
    ("verdict == 'FAIL'", True),
    ("verdict != \"PASS\"", True),
    ("unknown.field == null", True),
    ("findings.count > 2.5", True),
    ("true", True),
])
def test_expressions(expr, expected):
    assert evaluate(expr, CTX) is expected


@pytest.mark.parametrize("bad", [
    "__import__('os')", "findings.count >", "a.b()", "findings.count = 1", "1 +", "'unterminated", "x[0]",
    "a" * 2001,
])
def test_invalid_expressions_rejected(bad):
    with pytest.raises(ExpressionError):
        parse(bad)


def test_no_python_eval_semantics():
    # attribute access never reaches Python objects
    assert evaluate("findings.__class__ == null", CTX) is True


def test_template_substitutes_known_values_and_blanks_unknown():
    out = render_template("Найдено {{findings.count}}, critical {{ severity.critical }}, {{nope.x}}!", CTX)
    assert out == "Найдено 7, critical 0, !"


def test_template_does_not_evaluate_code():
    assert render_template("{{ findings.count + 1 }} {{__import__}}", CTX) == "{{ findings.count + 1 }} "
