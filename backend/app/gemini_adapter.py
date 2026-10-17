"""Google Gemini REST API adapter for the provider-neutral recipe boundary."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .recipe_schema import RECIPE_RESPONSE_SCHEMA


DEFAULT_MODEL = "gemini-3.5-flash-lite"
REQUEST_TIMEOUT_SECONDS = 25
MAX_PROVIDER_RESPONSE_BYTES = 100_000

class GeminiRecipeJsonClient:
    """Call Gemini Generate Content without exposing provider types upstream."""

    def __init__(self, api_key: str, model: str, opener=urlopen):
        self._api_key = api_key
        self._model = model
        self._opener = opener

    def request_json(self, system_instruction: str, input_json: str) -> str:
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{quote(self._model, safe='-_.')}:generateContent"
        )
        request_body = {
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": [{"role": "user", "parts": [{"text": input_json}]}],
            "generationConfig": {
                "responseFormat": {
                    "text": {
                        "mimeType": "APPLICATION_JSON",
                        "schema": RECIPE_RESPONSE_SCHEMA,
                    }
                },
                "temperature": 0.3,
                "maxOutputTokens": 2048,
            },
        }
        request = Request(
            endpoint,
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self._api_key},
            method="POST",
        )
        try:
            with self._opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                raw_response = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
            if len(raw_response) > MAX_PROVIDER_RESPONSE_BYTES:
                raise ValueError("Gemini response is too large")
            payload = json.loads(raw_response)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError("Gemini API request failed") from error

        candidates = payload.get("candidates") if isinstance(payload, dict) else None
        if not isinstance(candidates, list) or not candidates:
            raise RuntimeError("Gemini returned no recipe candidate")
        parts = candidates[0].get("content", {}).get("parts", [])
        output = "".join(
            part.get("text", "") for part in parts if isinstance(part, dict)
        ) if isinstance(parts, list) else ""
        if not output.strip():
            raise RuntimeError("Gemini returned empty text")
        return output


def create_client() -> GeminiRecipeJsonClient:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Задайте GEMINI_API_KEY для подключения Gemini API.")

    model = os.getenv("SMARTBITE_GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    return GeminiRecipeJsonClient(api_key, model)
