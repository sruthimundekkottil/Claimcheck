# Claimcheck

Spec-driven auditor for AI assistants. See [DESIGN.md](DESIGN.md).

## Setup

```sh
conda activate claimcheck
pip install -e ".[dev]"
git config core.hooksPath .githooks   # strips Claude attribution lines from commit messages
```

## Tests

```sh
pytest
```

The suite uses the mock gateway and needs no API key. Real runs read `GEMINI_API_KEY` and `GROQ_API_KEY`;
model ids and rate limits are in `config/models.yaml`. Free-tier prompts may be used by the providers to
improve their products; the project holds no personal data.
