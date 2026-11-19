import json

import pytest
import yaml
from pydantic import BaseModel

from auditor.gateway import Gateway, GatewayError, MockTransport


class Answer(BaseModel):
    verdict: str
    reason: str


MESSAGES = [{"role": "user", "content": "Is the sky blue?"}]
GOOD = json.dumps({"verdict": "pass", "reason": "yes"})


@pytest.fixture
def config(tmp_path):
    # Fake providers and ids: tests never reach a real model.
    cfg = {
        "retry": {"attempts": 2, "backoff_seconds": 0},
        "providers": {
            "first": {"base_url": "http://unused", "api_key_env": "NONE", "requests_per_minute": 6000},
            "second": {"base_url": "http://unused", "api_key_env": "NONE", "requests_per_minute": 6000},
        },
        "models": {"judge": [{"provider": "first", "id": "model-a"}, {"provider": "second", "id": "model-b"}]},
    }
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


def make(config, tmp_path, reply):
    transport = MockTransport(reply)
    return Gateway(config, tmp_path / "cache.sqlite", transport), transport


def test_returns_parsed_schema(config, tmp_path):
    gw, _ = make(config, tmp_path, lambda *a: GOOD)
    out = gw.complete(MESSAGES, "judge", Answer)
    assert out == Answer(verdict="pass", reason="yes")


def test_repeated_call_returns_from_cache(config, tmp_path):
    gw, transport = make(config, tmp_path, lambda *a: GOOD)
    first = gw.complete(MESSAGES, "judge", Answer)
    second = gw.complete(MESSAGES, "judge", Answer)
    assert first == second
    assert len(transport.calls) == 1


def test_cache_survives_a_new_gateway(config, tmp_path):
    gw, _ = make(config, tmp_path, lambda *a: GOOD)
    gw.complete(MESSAGES, "judge", Answer)
    gw2, transport2 = make(config, tmp_path, lambda *a: GOOD)
    gw2.complete(MESSAGES, "judge", Answer)
    assert transport2.calls == []


def test_different_messages_miss_cache(config, tmp_path):
    gw, transport = make(config, tmp_path, lambda *a: GOOD)
    gw.complete(MESSAGES, "judge", Answer)
    gw.complete([{"role": "user", "content": "Other"}], "judge", Answer)
    assert len(transport.calls) == 2


def test_retries_then_succeeds(config, tmp_path):
    replies = iter([RuntimeError("429"), GOOD])

    def reply(*a):
        r = next(replies)
        if isinstance(r, Exception):
            raise r
        return r

    gw, transport = make(config, tmp_path, reply)
    assert gw.complete(MESSAGES, "judge", Answer).verdict == "pass"
    assert [c[1] for c in transport.calls] == ["model-a", "model-a"]


def test_fails_over_to_second_provider(config, tmp_path):
    def reply(provider, model_id, messages, schema):
        if provider == "first":
            raise RuntimeError("daily cap")
        return GOOD

    gw, transport = make(config, tmp_path, reply)
    assert gw.complete(MESSAGES, "judge", Answer).verdict == "pass"
    assert [c[1] for c in transport.calls] == ["model-a", "model-a", "model-b"]


def test_invalid_json_is_retried_and_not_cached(config, tmp_path):
    gw, transport = make(config, tmp_path, lambda *a: '{"verdict": "pass"}')
    with pytest.raises(GatewayError):
        gw.complete(MESSAGES, "judge", Answer)
    assert len(transport.calls) == 4  # 2 attempts x 2 providers
    with pytest.raises(GatewayError):
        gw.complete(MESSAGES, "judge", Answer)
    assert len(transport.calls) == 8


def test_unknown_model_role(config, tmp_path):
    gw, _ = make(config, tmp_path, lambda *a: GOOD)
    with pytest.raises(GatewayError):
        gw.complete(MESSAGES, "nope", Answer)


def test_real_config_loads(tmp_path):
    gw = Gateway("config/models.yaml", tmp_path / "c.sqlite", MockTransport(lambda *a: GOOD))
    assert gw.complete(MESSAGES, "judge", Answer).verdict == "pass"


class AnswerV2(BaseModel):
    verdict: str
    reason: str
    severity: int


def test_schema_change_misses_cache(config, tmp_path):
    def reply(provider, model_id, messages, schema):
        return GOOD if schema is Answer else json.dumps({"verdict": "pass", "reason": "yes", "severity": 2})

    gw, transport = make(config, tmp_path, reply)
    gw.complete(MESSAGES, "judge", Answer)
    assert gw.complete(MESSAGES, "judge", AnswerV2).severity == 2
    assert len(transport.calls) == 2


def test_stale_cache_hit_is_refetched(config, tmp_path):
    from pydantic import field_validator

    class Stricter(BaseModel):
        model_config = {"title": "Answer"}  # same title and fields, so same JSON schema and cache key
        verdict: str
        reason: str

        @field_validator("verdict")
        @classmethod
        def not_pass(cls, v):
            assert v != "pass"
            return v

    assert Stricter.model_json_schema() == Answer.model_json_schema()

    def reply(provider, model_id, messages, schema):
        return GOOD if schema is Answer else json.dumps({"verdict": "fail", "reason": "no"})

    gw, transport = make(config, tmp_path, reply)
    gw.complete(MESSAGES, "judge", Answer)
    assert gw.complete(MESSAGES, "judge", Stricter).verdict == "fail"
    assert len(transport.calls) == 2


def test_http_falls_back_to_json_mode(monkeypatch):
    import io
    import urllib.error
    import urllib.request

    from auditor import gateway

    sent = []

    def fake_urlopen(req, timeout):
        body = json.loads(req.data)
        sent.append(body)
        if body["response_format"]["type"] == "json_schema":
            raise urllib.error.HTTPError(req.full_url, 400, "json_schema unsupported", {}, io.BytesIO())
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": GOOD}}]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(gateway, "_no_json_schema", set())
    monkeypatch.setenv("FAKE_KEY", "x")
    provider = {"name": "p", "base_url": "http://unused", "api_key_env": "FAKE_KEY"}

    assert Answer.model_validate_json(gateway.http_transport(provider, "m", MESSAGES, Answer)).verdict == "pass"
    assert [b["response_format"]["type"] for b in sent] == ["json_schema", "json_object"]
    assert "JSON schema" in sent[1]["messages"][0]["content"]

    gateway.http_transport(provider, "m", MESSAGES, Answer)  # remembered: goes straight to JSON mode
    assert sent[2]["response_format"]["type"] == "json_object"
