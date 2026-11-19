"""Load a pack folder and check it. Every problem found is collected and raised together as one PackError."""

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from auditor.schemas import PackManifest, Rubric, Rule, Test


class PackError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


@dataclass
class Pack:
    path: Path
    manifest: PackManifest
    rubric: Rubric
    rules: list[Rule]
    tests: list[Test]
    warnings: list[str] = field(default_factory=list)  # problems that do not stop the pack loading


def _fmt(where: str, e: ValidationError) -> list[str]:
    return [f"{where}: {'.'.join(map(str, err['loc'])) or '-'}: {err['msg']}" for err in e.errors()]


def _parse(model: type[BaseModel], data, where: str, errors: list[str]):
    try:
        return model.model_validate(data)
    except ValidationError as e:
        errors += _fmt(where, e)


def _read_yaml(path: Path, errors: list[str]):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        errors.append(f"{path.name}: {e}")


def load_pack(path: str | Path) -> Pack:
    path = Path(path)
    errors: list[str] = []

    manifest = _parse(PackManifest, _read_yaml(path / "pack.yaml", errors), "pack.yaml", errors)
    rubric = _parse(Rubric, _read_yaml(path / "rubric.yaml", errors), "rubric.yaml", errors)

    rules: list[Rule] = []
    spec = _read_yaml(path / "spec.yaml", errors)
    if spec is not None and not isinstance(spec, list):
        errors.append("spec.yaml: must be a list of rules")
    for i, data in enumerate(spec if isinstance(spec, list) else []):
        rid = data.get("id", f"#{i + 1}") if isinstance(data, dict) else f"#{i + 1}"
        if rule := _parse(Rule, data, f"spec.yaml: rule {rid}", errors):
            rules.append(rule)

    tests: list[Test] = []
    try:
        lines = (path / "tests.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError as e:
        errors.append(f"tests.jsonl: {e}")
        lines = []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"tests.jsonl:{n}: invalid JSON: {e}")
            continue
        if test := _parse(Test, data, f"tests.jsonl:{n}", errors):
            tests.append(test)

    # Cross-file checks.
    for kind, ids in (("rule", [r.id for r in rules]), ("test", [t.id for t in tests])):
        for dup in sorted({i for i in ids if ids.count(i) > 1}):
            errors.append(f"duplicate {kind} id {dup}")
    if rubric:
        for r in rules:
            if r.dimension not in rubric.dimensions:
                errors.append(f"spec.yaml: rule {r.id}: dimension {r.dimension!r} is not in rubric.yaml")
    test_ids = {t.id for t in tests}
    for t in tests:
        if manifest and t.language not in manifest.languages:
            errors.append(f"tests.jsonl: test {t.id}: language {t.language!r} is not in pack.yaml languages")
        if t.variant_of is not None and t.variant_of not in test_ids:
            errors.append(f"tests.jsonl: test {t.id}: variant_of {t.variant_of!r} is not a test id")

    if errors:
        raise PackError(errors)

    # Category cross-check: a warning, since a pack still being written may have gaps.
    warnings: list[str] = []
    test_cats = {t.category for t in tests}
    rule_cats = {c for r in rules for c in r.categories}
    for r in rules:
        for c in r.categories:
            if c not in test_cats:
                warnings.append(f"spec.yaml: rule {r.id}: category {c!r} is used by no test")
    for t in tests:
        if t.category not in rule_cats:
            warnings.append(f"tests.jsonl: test {t.id}: category {t.category!r} is listed by no rule")
    return Pack(path, manifest, rubric, rules, tests, warnings)
