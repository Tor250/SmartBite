import pytest

from app.application import recipes as recipe_application
from app.application.recipes import (
    GenerateRecipeCommand,
    RecipeRequestError,
    RecipeSafetyCheckError,
    generate_recipe,
)
from app.generator import DemoRecipeGenerator, RecipeDraft, RecipeIngredient, RecipeStep


def command(**overrides):
    values = {
        "mode": "from_products",
        "products": ["рис", "томат"],
        "description": None,
        "preferences": ["без жарки"],
        "exclusions": [],
    }
    values.update(overrides)
    return GenerateRecipeCommand(**values)


def test_use_case_passes_user_preferences_to_generator():
    recipe = generate_recipe(command(), DemoRecipeGenerator())

    assert recipe.title
    assert [item.name for item in recipe.ingredients] == ["рис", "томат"]


def test_use_case_rejects_empty_inventory_request():
    with pytest.raises(RecipeRequestError, match="Укажите продукты"):
        generate_recipe(command(products=[]), DemoRecipeGenerator())


def test_use_case_rejects_empty_preferences_request():
    with pytest.raises(RecipeRequestError, match="Опишите пожелания"):
        generate_recipe(command(mode="preferences", description=None, preferences=[]), DemoRecipeGenerator())


def test_use_case_rejects_unknown_request_mode():
    with pytest.raises(RecipeRequestError, match="поддерживаемый тип"):
        generate_recipe(command(mode="unknown"), DemoRecipeGenerator())


def test_use_case_does_not_return_candidate_that_matches_exclusion():
    with pytest.raises(RecipeRequestError, match="исключение"):
        generate_recipe(command(exclusions=["рис"]), DemoRecipeGenerator())


def test_use_case_fails_closed_when_exclusion_check_raises(monkeypatch):
    def failed_check(*_args, **_kwargs):
        raise RuntimeError("internal checker detail")

    monkeypatch.setattr(recipe_application, "check_ingredients", failed_check)
    with pytest.raises(RecipeSafetyCheckError, match="Рецепт не показан") as error:
        generate_recipe(command(), DemoRecipeGenerator())
    assert "internal checker detail" not in str(error.value)


def test_use_case_rejects_incomplete_generator_output():
    class BrokenGenerator:
        def generate(self, mode, products, preferences, description):
            return RecipeDraft("", [], None, [], [])

    with pytest.raises(RecipeRequestError, match="неполный рецепт"):
        generate_recipe(command(), BrokenGenerator())


def test_use_case_rejects_ingredient_that_was_not_in_the_inventory():
    class GeneratorWithExtraIngredient:
        def generate(self, mode, products, preferences, description):
            return RecipeDraft(
                "Рис с молоком",
                [RecipeIngredient("рис", "100 г"), RecipeIngredient("молоко", "100 мл")],
                None,
                [RecipeStep("Смешайте продукты.")],
                [],
            )

    with pytest.raises(RecipeRequestError, match="нет в вашем списке"):
        generate_recipe(command(), GeneratorWithExtraIngredient())


def test_use_case_rejects_exclusion_mentioned_only_in_preparation_steps():
    class GeneratorWithHiddenExclusion:
        def generate(self, mode, products, preferences, description):
            return RecipeDraft(
                "Рис с томатами",
                [RecipeIngredient("рис", "100 г"), RecipeIngredient("томат", "1 шт.")],
                None,
                [RecipeStep("Добавьте молоко и перемешайте.")],
                [],
            )

    with pytest.raises(RecipeRequestError, match="упоминание пищевого исключения"):
        generate_recipe(command(exclusions=["молоко"]), GeneratorWithHiddenExclusion())


def test_use_case_rejects_known_product_mentioned_only_in_preparation_steps():
    class GeneratorWithUnlistedStepIngredient:
        def generate(self, mode, products, preferences, description):
            return RecipeDraft(
                "Рис с томатом",
                [RecipeIngredient("рис", "100 г"), RecipeIngredient("томат", "1 шт.")],
                None,
                [RecipeStep("Добавьте картофель и перемешайте.")],
                [],
            )

    with pytest.raises(RecipeRequestError, match="нет в списке ингредиентов"):
        generate_recipe(command(), GeneratorWithUnlistedStepIngredient())


def test_use_case_rejects_non_quantity_text_in_quantity_field():
    class GeneratorWithHiddenIngredient:
        def generate(self, mode, products, preferences, description):
            return RecipeDraft(
                "Рис с томатами",
                [RecipeIngredient("рис", "100 г молока"), RecipeIngredient("томат", "1 шт.")],
                None,
                [RecipeStep("Приготовьте продукты.")],
                [],
            )

    with pytest.raises(RecipeRequestError, match="количество одного из ингредиентов"):
        generate_recipe(command(), GeneratorWithHiddenIngredient())


def test_use_case_keeps_ingredient_quantities_and_allows_missing_cooking_time():
    class GeneratorWithQuantities:
        def generate(self, mode, products, preferences, description):
            return RecipeDraft(
                "Рис с томатом",
                [RecipeIngredient("рис", "100 г"), RecipeIngredient("томат", "1 шт.")],
                None,
                [RecipeStep("Приготовьте продукты.")],
                [],
            )

    recipe = generate_recipe(command(), GeneratorWithQuantities())

    assert recipe.ingredients[0].quantity == "100 г"
    assert recipe.preparation_time_minutes is None


@pytest.mark.parametrize(
    ("total_time", "step_time", "error_text"),
    [
        (0, 5, "время приготовления"),
        (True, 5, "время приготовления"),
        (20, 0, "время шага"),
        (20, True, "время шага"),
    ],
)
def test_use_case_rejects_invalid_recipe_and_step_times(total_time, step_time, error_text):
    class GeneratorWithInvalidTime:
        def generate(self, mode, products, preferences, description):
            return RecipeDraft(
                "Рис с томатом",
                [RecipeIngredient("рис", "100 г"), RecipeIngredient("томат", "1 шт.")],
                total_time,
                [RecipeStep("Приготовьте продукты.", step_time)],
                [],
            )

    with pytest.raises(RecipeRequestError, match=error_text):
        generate_recipe(command(), GeneratorWithInvalidTime())
