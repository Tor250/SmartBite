import json
import logging
import sys
from types import ModuleType

import pytest

from app.generator import (
    DemoRecipeGenerator,
    RecipeGenerationError,
    StructuredRecipeGenerator,
    configured_recipe_generator,
)
from app.observability import request_id_context


def test_from_products_demo_uses_only_products_user_provided():
    recipe = DemoRecipeGenerator().generate("from_products", ["рис", "томат"], [], None)

    assert [item.name for item in recipe.ingredients] == ["рис", "томат"]
    assert recipe.missing_products == []
    assert all(step.duration_minutes is None for step in recipe.steps)


def test_preferences_demo_marks_itself_as_a_fixed_recipe_in_its_title():
    recipe = DemoRecipeGenerator().generate("preferences", ["рис"], ["без жарки"], "овощной ужин")

    assert recipe.title.startswith("Демонстрационный")
    assert [item.name for item in recipe.ingredients] == ["рис", "томат", "лук"]
    assert "томат" in recipe.missing_products
    assert "лук" in recipe.missing_products


def valid_recipe_payload():
    return {
        "title": "Рис с томатами",
        "preparation_time_minutes": 20,
        "ingredients": [
            {"name": "рис", "quantity": "100 г"},
            {"name": "томат", "quantity": "1 шт."},
        ],
        "steps": [
            {"instruction": "Промойте рис.", "duration_minutes": 2},
            {"instruction": "Приготовьте рис с томатами.", "duration_minutes": 18},
        ],
        "missing_products": [],
    }


class FakeRecipeJsonClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def request_json(self, system_instruction, input_json):
        self.calls.append((system_instruction, input_json))
        if self.error:
            raise self.error
        return self.response


def test_structured_generator_parses_ingredients_overall_and_step_times_and_traces(caplog):
    caplog.set_level(logging.INFO, logger="smartbite.generator")
    client = FakeRecipeJsonClient(json.dumps(valid_recipe_payload(), ensure_ascii=False))
    request_token = request_id_context.set("generation-trace-7")
    try:
        recipe = StructuredRecipeGenerator(client).generate(
            "from_products", ["рис", "томат"], ["без жарки"], "ужин"
        )
    finally:
        request_id_context.reset(request_token)

    system_instruction, input_json = client.calls[0]
    assert "duration_minutes" in system_instruction
    assert "preparation_time_minutes" in system_instruction
    assert json.loads(input_json) == {
        "products": ["рис", "томат"],
        "preferences": ["без жарки"],
        "description": "ужин",
    }
    assert "без жарки" in input_json
    assert "ужин" in input_json
    assert recipe.preparation_time_minutes == 20
    assert [item.name for item in recipe.ingredients] == ["рис", "томат"]
    assert recipe.ingredients[0].quantity == "100 г"
    assert recipe.steps[0].instruction == "Промойте рис."
    assert recipe.steps[0].duration_minutes == 2
    assert recipe.steps[1].duration_minutes == 18

    log_record = next(record for record in caplog.records if record.name == "smartbite.generator")
    assert '"request_id":"generation-trace-7"' in log_record.message
    assert "рис" not in log_record.message


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.update(title=""),
        lambda data: data.update(ingredients=[]),
        lambda data: data.update(steps=[]),
        lambda data: data["ingredients"][0].update(quantity="100 г молока"),
        lambda data: data["steps"][0].update(duration_minutes=0),
        lambda data: data["steps"][0].update(duration_minutes=True),
        lambda data: data.update(preparation_time_minutes=-1),
        lambda data: data["steps"][0].update(instruction=""),
    ],
)
def test_structured_generator_rejects_invalid_fields(mutate):
    data = valid_recipe_payload()
    mutate(data)
    generator = StructuredRecipeGenerator(FakeRecipeJsonClient(json.dumps(data, ensure_ascii=False)))

    with pytest.raises(RecipeGenerationError):
        generator.generate("from_products", ["рис", "томат"], [], None)


@pytest.mark.parametrize("response", ["not-json", "[]", "{}", None, " " * 50_001])
def test_structured_generator_rejects_invalid_json_or_root_type(response):
    generator = StructuredRecipeGenerator(FakeRecipeJsonClient(response))

    with pytest.raises(RecipeGenerationError, match="недоступен"):
        generator.generate("from_products", ["рис"], [], None)


def test_structured_generator_maps_adapter_failure_to_safe_error():
    generator = StructuredRecipeGenerator(FakeRecipeJsonClient(error=RuntimeError("secret endpoint")))

    with pytest.raises(RecipeGenerationError, match="недоступен") as error:
        generator.generate("from_products", ["рис"], [], None)
    assert "secret endpoint" not in str(error.value)


def test_structured_generator_requires_request_data_for_selected_mode():
    generator = StructuredRecipeGenerator(FakeRecipeJsonClient("{}"))

    with pytest.raises(RecipeGenerationError, match="пожелания"):
        generator.generate("preferences", ["рис"], [], None)
    with pytest.raises(RecipeGenerationError, match="продукты"):
        generator.generate("from_products", [], [], None)


def test_structured_generator_supports_preferences_mode_and_returns_shopping_list():
    data = valid_recipe_payload()
    data["missing_products"] = ["томат"]
    client = FakeRecipeJsonClient(json.dumps(data, ensure_ascii=False))

    recipe = StructuredRecipeGenerator(client).generate(
        "preferences", ["рис"], ["без мяса"], "быстрый ужин"
    )

    prompt, input_json = client.calls[0]
    assert "missing_products" in prompt
    assert json.loads(input_json)["preferences"] == ["без мяса"]
    assert recipe.missing_products == ["томат"]


@pytest.mark.parametrize("missing", [None, [""], ["x" * 101], ["рис"] * 41])
def test_structured_generator_rejects_invalid_missing_products(missing):
    data = valid_recipe_payload()
    data["missing_products"] = missing
    generator = StructuredRecipeGenerator(FakeRecipeJsonClient(json.dumps(data, ensure_ascii=False)))

    with pytest.raises(RecipeGenerationError):
        generator.generate("from_products", ["рис", "томат"], [], None)


def test_generator_configuration_uses_demo_until_adapter_is_selected(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("SMARTBITE_GENERATOR_ADAPTER", raising=False)
    assert isinstance(configured_recipe_generator(), DemoRecipeGenerator)


def test_qwen_key_does_not_replace_gemini_default_without_explicit_selection(monkeypatch):
    from app import qwen_adapter

    adapter = FakeRecipeJsonClient(json.dumps(valid_recipe_payload(), ensure_ascii=False))
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-test-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("SMARTBITE_GENERATOR_ADAPTER", raising=False)
    monkeypatch.setattr(qwen_adapter, "create_client", lambda: adapter)

    configured = configured_recipe_generator()

    assert isinstance(configured, DemoRecipeGenerator)


def test_qwen_can_be_selected_explicitly(monkeypatch):
    from app import qwen_adapter

    adapter = FakeRecipeJsonClient(json.dumps(valid_recipe_payload(), ensure_ascii=False))
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-test-key")
    monkeypatch.setenv("SMARTBITE_GENERATOR_ADAPTER", "app.qwen_adapter:create_client")
    monkeypatch.setattr(qwen_adapter, "create_client", lambda: adapter)

    configured = configured_recipe_generator()

    assert isinstance(configured, StructuredRecipeGenerator)
    assert configured.client is adapter


def test_gemini_remains_default_when_both_provider_keys_are_configured(monkeypatch):
    from app import gemini_adapter, qwen_adapter

    gemini = FakeRecipeJsonClient(json.dumps(valid_recipe_payload(), ensure_ascii=False))
    qwen = FakeRecipeJsonClient(json.dumps(valid_recipe_payload(), ensure_ascii=False))
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-test-key")
    monkeypatch.delenv("SMARTBITE_GENERATOR_ADAPTER", raising=False)
    monkeypatch.setattr(gemini_adapter, "create_client", lambda: gemini)
    monkeypatch.setattr(qwen_adapter, "create_client", lambda: qwen)

    configured = configured_recipe_generator()

    assert isinstance(configured, StructuredRecipeGenerator)
    assert configured.client is gemini


def test_generator_configuration_accepts_a_provider_neutral_adapter():
    adapter = FakeRecipeJsonClient(json.dumps(valid_recipe_payload(), ensure_ascii=False))

    assert isinstance(configured_recipe_generator(adapter), StructuredRecipeGenerator)


def test_generator_configuration_loads_operator_selected_adapter(monkeypatch):
    module = ModuleType("smartbite_test_adapter")
    adapter = FakeRecipeJsonClient(json.dumps(valid_recipe_payload(), ensure_ascii=False))
    module.create_client = lambda: adapter
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setenv("SMARTBITE_GENERATOR_ADAPTER", "smartbite_test_adapter:create_client")

    configured = configured_recipe_generator()

    assert isinstance(configured, StructuredRecipeGenerator)
    assert configured.client is adapter


@pytest.mark.parametrize(
    "adapter_path",
    ["missing-separator", "missing.module:create_client", "smartbite_test_adapter:missing_factory"],
)
def test_generator_configuration_fails_loudly_for_invalid_adapter(monkeypatch, adapter_path):
    monkeypatch.setenv("SMARTBITE_GENERATOR_ADAPTER", adapter_path)

    with pytest.raises(RuntimeError, match="Не удалось загрузить адаптер|должен иметь вид") as error:
        configured_recipe_generator()

    assert "secret" not in str(error.value)
