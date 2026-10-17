import json

import pytest

from app.qwen_adapter import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    MAX_PROVIDER_RESPONSE_BYTES,
    QWEN_RECIPE_RESPONSE_SCHEMA,
    REQUEST_TIMEOUT_SECONDS,
    QwenRecipeJsonClient,
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


def test_qwen_adapter_posts_strict_schema_request_and_returns_text():
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse({"choices": [{"message": {"content": '{"title":"Суп"}'}}]})

    response = QwenRecipeJsonClient("secret-key", "qwen-test", opener=opener).request_json(
        "Составь рецепт", '{"products":["картофель"]}'
    )

    assert response == '{"title":"Суп"}'
    assert captured["url"] == f"{DEFAULT_BASE_URL}/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret-key"
    assert captured["timeout"] == REQUEST_TIMEOUT_SECONDS
    assert captured["body"]["model"] == "qwen-test"
    assert captured["body"]["messages"] == [
        {"role": "system", "content": "Составь рецепт"},
        {"role": "user", "content": '{"products":["картофель"]}'},
    ]
    response_format = captured["body"]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"] == QWEN_RECIPE_RESPONSE_SCHEMA
    assert "secret-key" not in json.dumps(captured["body"])


@pytest.mark.parametrize("payload", [{}, {"choices": []}, {"choices": [{"message": {"content": ""}}]}])
def test_qwen_adapter_rejects_missing_or_empty_candidate(payload):
    adapter = QwenRecipeJsonClient("key", "model", opener=lambda *_a, **_k: FakeResponse(payload))

    with pytest.raises(RuntimeError):
        adapter.request_json("instruction", "{}")


def test_qwen_adapter_limits_response_size():
    class OversizedResponse(FakeResponse):
        def read(self, _limit):
            return b"x" * (MAX_PROVIDER_RESPONSE_BYTES + 1)

    adapter = QwenRecipeJsonClient(
        "key", "model", opener=lambda *_a, **_k: OversizedResponse({})
    )

    with pytest.raises(RuntimeError, match="request failed"):
        adapter.request_json("instruction", "{}")


def test_qwen_adapter_hides_network_error_details():
    adapter = QwenRecipeJsonClient(
        "key", "model", opener=lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError("private"))
    )

    with pytest.raises(RuntimeError, match="request failed") as error:
        adapter.request_json("instruction", "{}")
    assert "private" not in str(error.value)


def test_qwen_factory_requires_key_without_exposing_it(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
        create_client()


def test_qwen_factory_reads_model_and_endpoint_from_environment(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setenv("SMARTBITE_QWEN_MODEL", "qwen-test")
    monkeypatch.setenv("SMARTBITE_QWEN_BASE_URL", "https://custom.example/v1/")

    client = create_client()

    assert client._model == "qwen-test"
    assert client._base_url == "https://custom.example/v1"


def test_qwen_default_model_supports_structured_output():
    assert DEFAULT_MODEL == "qwen3.8-flash"
