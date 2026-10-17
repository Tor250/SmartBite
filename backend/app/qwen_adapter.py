"""Qwen REST adapter for the provider-neutral recipe generation boundary."""
import copy
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .recipe_schema import RECIPE_RESPONSE_SCHEMA


DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.8-flash"
REQUEST_TIMEOUT_SECONDS = 25
MAX_PROVIDER_RESPONSE_BYTES = 100_000


def _strict_schema() -> dict:
    """Return the shared recipe schema with Qwen's strict-object constraints."""
    schema = copy.deepcopy(RECIPE_RESPONSE_SCHEMA)

    def close_objects(node: dict) -> None:
        if node.get("type") == "object":
            node["additionalProperties"] = False
            for child in node.get("properties", {}).values():
                close_objects(child)
        items = node.get("items")
        if isinstance(items, dict):
            close_objects(items)

    close_objects(schema)
    return schema


QWEN_RECIPE_RESPONSE_SCHEMA = _strict_schema()


class QwenRecipeJsonClient:
    """Call Alibaba Model Studio's OpenAI-compatible chat completions API."""

    def __init__(self, api_key: str, model: str, base_url: str = DEFAULT_BASE_URL, opener=urlopen):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._opener = opener

    def request_json(self, system_instruction: str, input_json: str) -> str:
        request_body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": input_json},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "smartbite_recipe",
                    "strict": True,
                    "schema": QWEN_RECIPE_RESPONSE_SCHEMA,
                },
            },
        }
        request = Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                raw_response = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
            if len(raw_response) > MAX_PROVIDER_RESPONSE_BYTES:
                raise ValueError("Qwen response is too large")
            payload = json.loads(raw_response)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError("Qwen API request failed") from error

        choices = payload.get("choices") if isinstance(payload, dict) else None
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("Qwen returned no recipe candidate")
        message = choices[0].get("message", {})
        output = message.get("content", "") if isinstance(message, dict) else ""
        if not isinstance(output, str) or not output.strip():
            raise RuntimeError("Qwen returned empty text")
        return output


def create_client() -> QwenRecipeJsonClient:
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Задайте DASHSCOPE_API_KEY для подключения Qwen API.")

    model = os.getenv("SMARTBITE_QWEN_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    base_url = os.getenv("SMARTBITE_QWEN_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    return QwenRecipeJsonClient(api_key, model, base_url)
