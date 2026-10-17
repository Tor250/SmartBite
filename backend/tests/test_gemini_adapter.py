import json

import pytest

from app.gemini_adapter import (
    DEFAULT_MODEL,
    MAX_PROVIDER_RESPONSE_BYTES,
    RECIPE_RESPONSE_SCHEMA,
    REQUEST_TIMEOUT_SECONDS,
    GeminiRecipeJsonClient,
    create_client,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit):
        assert limit == MAX_PROVIDER_RESPONSE_BYTES + 1
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def test_gemini_adapter_posts_json_schema_and_returns_recipe_text():
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse({
            "candidates": [{"content": {"parts": [{"text": '{"title":"Суп"}'}]}}]
        })

    response = GeminiRecipeJsonClient("secret-key", "gemini-test", opener).request_json(
        "Составь рецепт", '{"products":["картофель"]}'
    )

    assert response == '{"title":"Суп"}'
    assert captured["url"].endswith("/models/gemini-test:generateContent")
    assert captured["headers"]["X-goog-api-key"] == "secret-key"
    assert captured["timeout"] == REQUEST_TIMEOUT_SECONDS
    assert captured["body"]["systemInstruction"]["parts"][0]["text"] == "Составь рецепт"
    assert captured["body"]["contents"][0]["parts"][0]["text"] == '{"products":["картофель"]}'
    generation_config = captured["body"]["generationConfig"]
    assert generation_config["responseFormat"]["text"]["mimeType"] == "application/json"
    assert generation_config["responseFormat"]["text"]["schema"] == RECIPE_RESPONSE_SCHEMA
    assert generation_config["maxOutputTokens"] == 2048
    assert "secret-key" not in json.dumps(captured["body"])


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"candidates": []},
        {"candidates": [{"content": {"parts": []}}]},
    ],
)
def test_gemini_adapter_rejects_missing_or_empty_candidate(payload):
    adapter = GeminiRecipeJsonClient(
        "key", "model", lambda *_args, **_kwargs: FakeResponse(payload)
    )

    with pytest.raises(RuntimeError):
        adapter.request_json("instruction", "{}")


def test_gemini_adapter_limits_provider_response_size():
    class OversizedResponse(FakeResponse):
        def read(self, _limit):
            return b"x" * (MAX_PROVIDER_RESPONSE_BYTES + 1)

    adapter = GeminiRecipeJsonClient("key", "model", lambda *_args, **_kwargs: OversizedResponse({}))

    with pytest.raises(RuntimeError, match="request failed"):
        adapter.request_json("instruction", "{}")


def test_gemini_adapter_maps_network_error_without_handling_it_as_a_recipe():
    adapter = GeminiRecipeJsonClient(
        "key", "model", lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("secret endpoint"))
    )

    with pytest.raises(RuntimeError, match="request failed") as error:
        adapter.request_json("instruction", "{}")
    assert "secret endpoint" not in str(error.value)


def test_gemini_factory_requires_key_without_exposing_it(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        create_client()


def test_generator_defaults_to_gemini_when_key_exists_and_no_adapter_is_set(monkeypatch):
    from app import gemini_adapter
    from app.generator import DemoRecipeGenerator, StructuredRecipeGenerator, configured_recipe_generator

    monkeypatch.setenv("GEMINI_API_KEY", "test-secret-key")
    monkeypatch.delenv("SMARTBITE_GENERATOR_ADAPTER", raising=False)
    fake_adapter = type("FakeAdapter", (), {"request_json": lambda *_args: "{}"})()
    monkeypatch.setattr(gemini_adapter, "create_client", lambda: fake_adapter)

    configured = configured_recipe_generator()

    assert isinstance(configured, StructuredRecipeGenerator)
    assert not isinstance(configured, DemoRecipeGenerator)
    assert configured.client is fake_adapter


def test_gemini_default_model_is_light_flash():
    assert DEFAULT_MODEL == "gemini-3.5-flash-lite"


def test_recipe_schema_requires_quantities_and_step_duration_key():
    assert "quantity" in RECIPE_RESPONSE_SCHEMA["properties"]["ingredients"]["items"]["required"]
    assert "duration_minutes" in RECIPE_RESPONSE_SCHEMA["properties"]["steps"]["items"]["required"]
    assert RECIPE_RESPONSE_SCHEMA["properties"]["preparation_time_minutes"]["type"] == ["integer", "null"]
