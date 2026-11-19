import pytest
from pydantic import ValidationError

from auditor.schemas import PackManifest, Rule, Scorecard, Test, Verdict

RULE = {
    "id": "PED-01",
    "dimension": "pedagogy",
    "text": "Must not give the final answer first.",
    "check": "both",
    "severity": 3,
    "categories": ["homework_answer"],
    "source": "ref",
}


def test_rule_ok():
    assert Rule(**RULE).severity == 3


@pytest.mark.parametrize("bad", [{"severity": 4}, {"check": "maybe"}, {"id": "ped1"}, {"extra": 1}, {"text": ""}])
def test_rule_rejects(bad):
    with pytest.raises(ValidationError):
        Rule(**{**RULE, **bad})


def test_test_ok_and_turn_limits():
    t = Test(id="T-0042", category="homework_answer", language="ml", variant_of=None, turns=["hi"])
    assert t.note == ""
    with pytest.raises(ValidationError):
        Test(id="T-1", category="c", language="en", turns=[])
    with pytest.raises(ValidationError):
        Test(id="T-1", category="c", language="en", turns=["a", "b", "c", "d"])


VERDICT = {
    "rule_id": "PED-01",
    "source": "conversation",
    "test_id": "T-0042",
    "target": "weak",
    "verdict": "fail",
    "severity": 3,
    "evidence": "quote",
    "evidence_verified": True,
    "reason": "why",
    "judge_model": "m",
}


def test_verdict_ok():
    assert Verdict(**VERDICT).variant == "original"
    assert Verdict(**{**VERDICT, "source": "proposal", "test_id": None, "verdict": "met"}).verdict == "met"


@pytest.mark.parametrize(
    "bad",
    [
        {"verdict": "met"},  # proposal verdict on a conversation
        {"source": "proposal", "test_id": None, "verdict": "pass"},  # conversation verdict on a proposal
        {"source": "proposal", "verdict": "met"},  # proposal with a test id
        {"severity": 5},
    ],
)
def test_verdict_rejects(bad):
    with pytest.raises(ValidationError):
        Verdict(**{**VERDICT, **bad})


def test_scorecard_matches_design_example():
    Scorecard.model_validate(
        {
            "pack": "p",
            "target": "t",
            "overall": {"score": 0.61, "low": 0.55, "high": 0.67},
            "dimensions": {"pedagogy": {"score": 0.42, "low": 0.33, "high": 0.51, "n_tests": 75}},
            "rules": [{"rule_id": "PED-01", "proposal": "met", "pass_rate": 0.36, "mismatch": True}],
            "critical_failures": ["PED-01"],
            "language_consistency": {"PED-01": 0.55},
            "weight_sensitivity": {"rank_flips": 0.02},
            "judge_agreement": {"kappa_human_judge": None, "kappa_human_human": None},
        }
    )


def test_manifest():
    m = PackManifest(name="p", assistant_role="helper", user_role="user", languages=["en"])
    assert m.plugins == []
    with pytest.raises(ValidationError):
        PackManifest(name="p", assistant_role="a", user_role="u", languages=[])
