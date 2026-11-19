import json
import shutil
from pathlib import Path

import pytest
import yaml

from auditor.cli import main
from auditor.pack import PackError, load_pack

EXAMPLE = Path(__file__).parents[1] / "packs" / "_example"


@pytest.fixture
def pack(tmp_path):
    """A writable copy of the example pack, so tests can break it."""
    return Path(shutil.copytree(EXAMPLE, tmp_path / "pack"))


def edit_yaml(path, change):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def add_test(pack, **fields):
    test = {"id": "T-NEW", "category": "dosing", "language": "en", "turns": ["hi"], **fields}
    with (pack / "tests.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(test) + "\n")


def errors_for(pack):
    with pytest.raises(PackError) as e:
        load_pack(pack)
    return "\n".join(e.value.errors)


def test_example_pack_loads():
    p = load_pack(EXAMPLE)
    assert p.manifest.name == "_example"
    assert [r.id for r in p.rules] == ["ACC-01", "SAF-01", "TRN-01"]
    assert set(p.rubric.dimensions) == {r.dimension for r in p.rules}
    assert len(p.tests) >= 3


def test_bad_severity_names_file_and_rule(pack):
    edit_yaml(pack / "spec.yaml", lambda rules: rules[1].update(severity=5))
    msg = errors_for(pack)
    assert "spec.yaml" in msg and "SAF-01" in msg and "severity" in msg


def test_unknown_dimension(pack):
    edit_yaml(pack / "spec.yaml", lambda rules: rules[0].update(dimension="nonsense"))
    assert "nonsense" in errors_for(pack)


def test_duplicate_rule_id(pack):
    edit_yaml(pack / "spec.yaml", lambda rules: rules.append(dict(rules[0])))
    assert "duplicate" in errors_for(pack)


def test_test_language_not_in_manifest(pack):
    add_test(pack, language="xx")
    assert "xx" in errors_for(pack)


def test_variant_of_unknown_test(pack):
    add_test(pack, variant_of="T-9999")
    assert "T-9999" in errors_for(pack)


def test_bad_tests_line_names_line_number(pack):
    with (pack / "tests.jsonl").open("a", encoding="utf-8") as f:
        f.write("{not json\n")
    assert "tests.jsonl:" in errors_for(pack)


def test_bad_rubric_severity_keys(pack):
    edit_yaml(pack / "rubric.yaml", lambda r: r["severity_multipliers"].pop(3))
    assert "rubric.yaml" in errors_for(pack)


def test_missing_file(pack):
    (pack / "pack.yaml").unlink()
    assert "pack.yaml" in errors_for(pack)


def test_all_errors_reported_at_once(pack):
    edit_yaml(pack / "spec.yaml", lambda rules: rules[0].update(dimension="nonsense"))
    add_test(pack, language="xx")
    msg = errors_for(pack)
    assert "nonsense" in msg and "xx" in msg


def test_example_pack_has_no_warnings():
    assert load_pack(EXAMPLE).warnings == []


def test_category_mismatch_warns_not_errors(pack):
    edit_yaml(pack / "spec.yaml", lambda rules: rules[2].update(categories=["unused_cat"]))
    add_test(pack, category="orphan_cat")
    warnings = "\n".join(load_pack(pack).warnings)
    assert "TRN-01" in warnings and "unused_cat" in warnings
    assert "T-NEW" in warnings and "orphan_cat" in warnings


def test_cli_validate_ok(capsys):
    assert main(["validate", str(EXAMPLE)]) == 0
    assert "OK" in capsys.readouterr().out


def test_cli_validate_prints_warnings_and_passes(pack, capsys):
    add_test(pack, category="orphan_cat")
    assert main(["validate", str(pack)]) == 0
    assert "warning" in capsys.readouterr().err


def test_cli_validate_rejects_broken_rule(pack, capsys):
    edit_yaml(pack / "spec.yaml", lambda rules: rules[0].update(check="sometimes"))
    assert main(["validate", str(pack)]) == 1
    assert "ACC-01" in capsys.readouterr().err
