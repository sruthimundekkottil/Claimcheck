"""The one LLM client. Every model call goes through Gateway.complete: disk cache, rate limit, retry, failover, mock."""

import hashlib
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml
from pydantic import BaseModel


class GatewayError(RuntimeError):
    pass


_no_json_schema = set()  # (provider, model id) pairs that rejected json_schema replies


def http_transport(provider: dict, model_id: str, messages: list[dict], schema: type[BaseModel]) -> str:
    """One call to an OpenAI-compatible chat endpoint; returns the reply text.

    Asks for a json_schema reply. If the endpoint rejects that (HTTP 400), it uses plain JSON mode from then on,
    with the schema given in the prompt; Gateway.complete validates the reply either way.
    """
    key = os.environ.get(provider["api_key_env"])
    if not key:
        raise GatewayError(f"environment variable {provider['api_key_env']} is not set")
    spec = schema.model_json_schema()
    if (provider["name"], model_id) not in _no_json_schema:
        fmt = {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": spec}}
        try:
            return _post(provider, key, {"model": model_id, "messages": messages, "temperature": 0, "response_format": fmt})
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise
            _no_json_schema.add((provider["name"], model_id))
    hint = {"role": "system", "content": "Reply with only a JSON object matching this JSON schema:\n" + json.dumps(spec)}
    body = {"model": model_id, "messages": [hint, *messages], "temperature": 0, "response_format": {"type": "json_object"}}
    return _post(provider, key, body)


def _post(provider, key, body):
    req = urllib.request.Request(
        provider["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)["choices"][0]["message"]["content"]


class MockTransport:
    """Canned replies for tests: reply(provider_name, model_id, messages, schema) -> str. Records every call."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def __call__(self, provider, model_id, messages, schema):
        self.calls.append((provider["name"], model_id, messages, schema))
        return self.reply(provider["name"], model_id, messages, schema)


class Gateway:
    def __init__(self, config_path="config/models.yaml", cache_path="runs/cache.sqlite", transport=http_transport):
        cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        self.retry = cfg["retry"]
        self.providers = {name: {**p, "name": name} for name, p in cfg["providers"].items()}
        self.models = cfg["models"]
        self.transport = transport
        self.last_call = {}  # provider name -> time of its last request
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(cache_path)
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, reply TEXT)")

    def complete(self, messages: list[dict], model: str, schema: type[BaseModel]) -> BaseModel:
        """Return the reply of the `model` role, parsed into `schema`. Cached replies cost no call."""
        if model not in self.models:
            raise GatewayError(f"no model role {model!r} in config")
        route = [(self.providers[m["provider"]], m["id"]) for m in self.models[model]]
        keys = [self._key(p, mid, messages, schema) for p, mid in route]

        for key in keys:
            row = self.db.execute("SELECT reply FROM cache WHERE key = ?", (key,)).fetchone()
            if row:
                try:
                    return schema.model_validate_json(row[0])
                except ValueError:
                    pass  # cached reply no longer fits the schema (e.g. a new validator): fetch again

        errors = []
        for (provider, model_id), key in zip(route, keys):
            for attempt in range(self.retry["attempts"]):
                if attempt:
                    time.sleep(self.retry["backoff_seconds"] * 2 ** (attempt - 1))
                self._wait_for_slot(provider)
                try:
                    text = self.transport(provider, model_id, messages, schema)
                    result = schema.model_validate_json(text)
                except (ValueError, RuntimeError, OSError, KeyError) as e:  # ValidationError is a ValueError
                    errors.append(f"{provider['name']}/{model_id}: {e}")
                    continue
                with self.db:
                    self.db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?)", (key, result.model_dump_json()))
                return result
        raise GatewayError("all models failed:\n" + "\n".join(errors))

    def _wait_for_slot(self, provider):
        gap = 60 / provider["requests_per_minute"]
        wait = self.last_call.get(provider["name"], 0) + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.last_call[provider["name"]] = time.monotonic()

    @staticmethod
    def _key(provider, model_id, messages, schema):
        settings = {"temperature": 0, "schema": schema.model_json_schema()}
        blob = json.dumps([provider["name"], model_id, messages, settings], sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()
