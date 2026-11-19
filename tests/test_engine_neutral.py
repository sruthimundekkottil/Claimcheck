import re
from pathlib import Path

ENGINE = Path(__file__).parents[1] / "src" / "auditor"
DOMAIN_TERMS = re.compile(
    r"educat|health|tutor|student|school|teacher|classroom|syllabus|textbook|"
    r"medic|patient|drug|clinic|malayalam|kerala|packs/",
    re.IGNORECASE,
)


def test_engine_has_no_domain_terms():
    hits = [
        f"{p.name}:{n}: {line.strip()}"
        for p in ENGINE.rglob("*.py")
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if DOMAIN_TERMS.search(line)
    ]
    assert hits == []
