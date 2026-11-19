"""Data formats passed between a pack and the engine. Unknown fields are rejected so a malformed pack fails at load time."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PackManifest(Strict):
    name: str
    assistant_role: str
    user_role: str
    languages: list[str] = Field(min_length=1)
    plugins: list[str] = []


class Rule(Strict):
    id: str = Field(pattern=r"^[A-Z]+-\d{2,}$")
    dimension: str  # checked against rubric.yaml when the pack loads
    text: str = Field(min_length=1)
    check: Literal["proposal", "conversation", "both"]
    severity: Literal[1, 2, 3]
    categories: list[str] = []
    source: str


class Test(Strict):
    __test__ = False  # stop pytest collecting this class

    id: str
    category: str
    language: str  # checked against the manifest's languages when the pack loads
    variant_of: str | None = None
    turns: list[str] = Field(min_length=1, max_length=3)
    note: str = ""


PROPOSAL_VERDICTS = {"met", "partial", "missing", "contradicted", "unverified"}
CONVERSATION_VERDICTS = {"pass", "fail", "not_applicable"}


class Verdict(Strict):
    rule_id: str
    source: Literal["proposal", "conversation"]
    test_id: str | None = None
    target: str
    verdict: Literal["met", "partial", "missing", "contradicted", "unverified", "pass", "fail", "not_applicable"]
    severity: int = Field(ge=0, le=3)
    evidence: str
    evidence_verified: bool
    reason: str
    judge_model: str
    variant: str = "original"

    @model_validator(mode="after")
    def _fits_source(self):
        allowed = PROPOSAL_VERDICTS if self.source == "proposal" else CONVERSATION_VERDICTS
        if self.verdict not in allowed:
            raise ValueError(f"verdict {self.verdict!r} is not valid for source {self.source!r}")
        if self.source == "proposal" and self.test_id:
            raise ValueError("a proposal verdict has no test_id")
        if self.source == "conversation" and not self.test_id:
            raise ValueError("a conversation verdict needs a test_id")
        return self


class Interval(Strict):
    score: float
    low: float
    high: float


class DimensionScore(Interval):
    n_tests: int


class RuleResult(Strict):
    rule_id: str
    proposal: str | None = None
    pass_rate: float | None = None
    mismatch: bool = False


class Scorecard(Strict):
    pack: str
    target: str
    overall: Interval
    dimensions: dict[str, DimensionScore]
    rules: list[RuleResult]
    critical_failures: list[str]
    language_consistency: dict[str, float] = {}
    weight_sensitivity: dict[str, float] = {}
    judge_agreement: dict[str, float | None] = {}
