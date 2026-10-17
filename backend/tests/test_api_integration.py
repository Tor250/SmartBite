import json
import logging

import pytest

from app import main
from app.application import recipes as recipe_application
from app.generator import (
    DemoRecipeGenerator,
    RecipeGenerationError,
    StructuredRecipeGenerator,
)
from app.generation_runner import GenerationBusy, GenerationTimedOut


def test_registration_profile_and_recipe_generation_flow(api_client):
    registration = api_client.post(
        "/api/auth/register",
        json={"email": "flow@example.org", "password": "strong-pass-123"},
    )
    assert registration.status_code == 201
    token = registration.json()["access_token"]
    headers = {"Authorization": "Bearer " + token}

    saved = api_client.put(
        "/api/profile",
        headers=headers,
        json={"preferences": ["без жарки"], "exclusions": ["молоко"]},
    )
    recipe = api_client.post(
        "/api/recipes/generate",
        headers=headers,
        json={"mode": "from_products", "products": ["рис", "томат"]},
    )
    blocked = api_client.post(
        "/api/recipes/generate",
        headers=headers,
        json={"mode": "from_products", "products": ["молоко", "рис"]},
    )

    assert saved.status_code == 200
    assert saved.json()["preferences"] == ["без жарки"]
    assert recipe.status_code == 200
    assert recipe.json()["generator"] == "demo"
    assert blocked.status_code == 422


def test_mvp_recipe_generation_works_without_account_and_returns_request_id(api_client):
    response = api_client.post(
        "/api/v1/recipes/generate",
        headers={"X-Request-ID": "presentation-demo-1"},
        json={"products": ["рис", "томат"], "exclusions": ["молоко"]},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "presentation-demo-1"
    assert response.json()["generator"] == "demo"
    assert [item["name"] for item in response.json()["ingredients"]] == ["рис", "томат"]
    assert all("quantity" in item for item in response.json()["ingredients"])


def test_browser_preflight_allows_request_correlation_header(api_client):
    response = api_client.request(
        "OPTIONS",
        "/api/v1/recipes/generate",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-request-id",
        },
    )

    assert response.status_code == 200
    assert "x-request-id" in response.headers["access-control-allow-headers"].lower()


def test_mvp_generation_blocks_an_excluded_ingredient_before_showing_recipe(api_client):
    response = api_client.post(
        "/api/v1/recipes/generate",
        json={"products": ["рис", "томат"], "exclusions": ["рис"]},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "RECIPE_REJECTED"
    assert "request_id" in response.json()


def test_mvp_generation_fails_closed_if_safety_check_crashes(api_client, monkeypatch):
    def failed_check(*_args, **_kwargs):
        raise RuntimeError("internal checker detail")

    monkeypatch.setattr(recipe_application, "check_ingredients", failed_check)
    response = api_client.post(
        "/api/v1/recipes/generate",
        json={"products": ["рис", "томат"], "exclusions": []},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "SAFETY_CHECK_UNAVAILABLE"
    assert "Рецепт не показан" in response.json()["message"]
    assert "internal checker detail" not in response.text


def test_mvp_generation_rejects_blank_inventory(api_client):
    response = api_client.post(
        "/api/v1/recipes/generate",
        json={"products": [], "exclusions": []},
    )

    assert response.status_code == 422
    assert "Укажите продукты" in response.json()["message"]


def test_mvp_generation_returns_safe_unavailable_error_without_candidate(api_client, monkeypatch):
    class DownGenerator:
        def generate(self, mode, products, preferences, description):
            raise RecipeGenerationError("do not expose provider details")

    monkeypatch.setattr(main, "generator", DownGenerator())
    response = api_client.post(
        "/api/v1/recipes/generate",
        json={"products": ["рис"], "exclusions": []},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "GENERATOR_UNAVAILABLE"
    assert "do not expose" not in response.text
    monkeypatch.setattr(main, "generator", DemoRecipeGenerator())


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (GenerationBusy(), "GENERATOR_BUSY"),
        (GenerationTimedOut(), "GENERATOR_TIMEOUT"),
    ],
)
def test_mvp_generation_returns_bounded_runner_errors(api_client, monkeypatch, failure, expected_code):
    class FailingRunner:
        async def run(self, *_args):
            raise failure

    monkeypatch.setattr(main, "generation_runner", FailingRunner())
    response = api_client.post(
        "/api/v1/recipes/generate",
        json={"products": ["рис", "томат"], "exclusions": []},
    )

    assert response.status_code == 503
    assert response.json()["code"] == expected_code
    assert response.json()["request_id"]


def test_mvp_api_parses_provider_json_and_correlates_generation(api_client, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="smartbite.generator")
    captured = {}

    class ProviderAdapter:
        def request_json(self, system_instruction, input_json):
            captured["system_instruction"] = system_instruction
            captured["input"] = json.loads(input_json)
            return json.dumps(
                {
                    "title": "Рис с томатами",
                    "preparation_time_minutes": 20,
                    "ingredients": [
                        {"name": "рис", "quantity": "100 г"},
                        {"name": "томат", "quantity": "1 шт."},
                    ],
                    "steps": [
                        {"instruction": "Промойте рис.", "duration_minutes": 2},
                        {"instruction": "Приготовьте с томатами.", "duration_minutes": 18},
                    ],
                },
                ensure_ascii=False,
            )

    monkeypatch.setattr(
        main,
        "generator",
        StructuredRecipeGenerator(ProviderAdapter()),
    )
    response = api_client.post(
        "/api/v1/recipes/generate",
        headers={"X-Request-ID": "trace-api-42"},
        json={"products": ["рис", "томат"], "exclusions": ["молоко"]},
    )

    assert response.status_code == 200
    assert response.json()["generator"] == "ai"
    assert response.headers["X-Request-ID"] == "trace-api-42"
    assert response.json()["preparation_time_minutes"] == 20
    assert captured["input"] == {"products": ["рис", "томат"]}
    assert "exclusions" not in captured["input"]
    assert response.json()["steps"][0] == {"instruction": "Промойте рис.", "duration_minutes": 2}
    assert response.json()["steps"][1]["duration_minutes"] == 18
    log_record = next(record for record in caplog.records if record.name == "smartbite.generator")
    assert '"request_id":"trace-api-42"' in log_record.message
    assert "рис" not in log_record.message


@pytest.mark.parametrize(
    ("ingredients", "steps", "exclusions", "expected_message"),
    [
        ([{"name": "рис", "quantity": "100 г"}, {"name": "молоко", "quantity": "100 мл"}],
         [{"instruction": "Смешайте продукты.", "duration_minutes": 2}],
         ["молоко"], "исключение"),
        ([{"name": "рис", "quantity": "100 г"}, {"name": "томат", "quantity": "1 шт."}],
         [{"instruction": "Приготовьте рис и томат.", "duration_minutes": 10}],
         [], "нет в вашем списке"),
        ([{"name": "рис", "quantity": "100 г"}],
         [{"instruction": "Добавьте немного молока и перемешайте.", "duration_minutes": 2}],
         ["молоко"], "упоминание пищевого исключения"),
    ],
)
def test_provider_candidate_is_blocked_when_safety_checks_fail(
    api_client, monkeypatch, ingredients, steps, exclusions, expected_message
):
    class ProviderAdapter:
        def request_json(self, _system_instruction, _input_json):
            return json.dumps(
                {
                    "title": "Кандидат, который нельзя показывать",
                    "preparation_time_minutes": 10,
                    "ingredients": ingredients,
                    "steps": steps,
                },
                ensure_ascii=False,
            )

    monkeypatch.setattr(main, "generator", StructuredRecipeGenerator(ProviderAdapter()))
    response = api_client.post(
        "/api/v1/recipes/generate",
        json={"products": ["рис"], "exclusions": exclusions},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "RECIPE_REJECTED"
    assert expected_message in response.json()["message"]
    assert "Кандидат, который нельзя показывать" not in response.text


def test_provider_recipe_is_blocked_when_step_adds_an_unlisted_known_ingredient(api_client, monkeypatch):
    class ProviderAdapter:
        def request_json(self, _system_instruction, _input_json):
            return json.dumps(
                {
                    "title": "Рис с томатами",
                    "preparation_time_minutes": 15,
                    "ingredients": [
                        {"name": "рис", "quantity": "100 г"},
                        {"name": "томат", "quantity": "1 шт."},
                    ],
                    "steps": [
                        {"instruction": "Добавьте картофель и перемешайте.", "duration_minutes": 5}
                    ],
                },
                ensure_ascii=False,
            )

    monkeypatch.setattr(main, "generator", StructuredRecipeGenerator(ProviderAdapter()))
    response = api_client.post(
        "/api/v1/recipes/generate",
        json={"products": ["рис", "томат"], "exclusions": []},
    )

    assert response.status_code == 422
    assert "нет в списке ингредиентов" in response.json()["message"]
    assert "Рис с томатами" not in response.text
