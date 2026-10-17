from dataclasses import dataclass

from ..generator import RecipeDraft, RecipeGenerator, RecipeIngredient, RecipeStep, is_valid_quantity
from ..safety import (
    canonical_name,
    check_ingredients,
    contains_excluded_name,
    mentioned_known_ingredients,
    normalize_ingredient_name,
)


class RecipeRequestError(ValueError):
    """The command is incomplete or the candidate cannot safely be shown."""


class RecipeSafetyCheckError(RuntimeError):
    """The checker failed, so the candidate must remain unavailable."""


@dataclass(frozen=True)
class GenerateRecipeCommand:
    mode: str
    products: list[str]
    description: str | None
    preferences: list[str]
    exclusions: list[str]


@dataclass(frozen=True)
class GeneratedRecipe:
    title: str
    ingredients: list[RecipeIngredient]
    preparation_time_minutes: int | None
    steps: list[RecipeStep]
    missing_products: list[str]


def generate_recipe(command: GenerateRecipeCommand, generator: RecipeGenerator) -> GeneratedRecipe:
    products = [item.strip() for item in command.products if item.strip()]
    preferences = [item.strip() for item in command.preferences if item.strip()]
    description = command.description.strip() if command.description else None

    if command.mode == "from_products" and not products:
        raise RecipeRequestError("Укажите продукты, которые есть дома.")
    if command.mode == "preferences" and not (description or preferences):
        raise RecipeRequestError("Опишите пожелания или выберите предпочтения в профиле.")
    if command.mode not in {"from_products", "preferences"}:
        raise RecipeRequestError("Выберите поддерживаемый тип запроса.")

    draft: RecipeDraft = generator.generate(command.mode, products, preferences, description)
    if not draft.title.strip() or not draft.steps:
        raise RecipeRequestError("Генератор вернул неполный рецепт.")
    if draft.preparation_time_minutes is not None and (
        isinstance(draft.preparation_time_minutes, bool)
        or not isinstance(draft.preparation_time_minutes, int)
        or not 1 <= draft.preparation_time_minutes <= 1440
    ):
        raise RecipeRequestError("Генератор вернул некорректное время приготовления.")
    ingredients = [
        RecipeIngredient(name=item.name.strip(), quantity=item.quantity.strip() if item.quantity else None)
        for item in draft.ingredients
    ]
    if not ingredients or any(not item.name for item in ingredients):
        raise RecipeRequestError("Генератор вернул неполный список ингредиентов.")
    if any(item.quantity is not None and not is_valid_quantity(item.quantity) for item in ingredients):
        raise RecipeRequestError("Не удалось проверить количество одного из ингредиентов.")
    steps = [item for item in draft.steps if isinstance(item, RecipeStep)]
    if len(steps) != len(draft.steps) or any(not item.instruction.strip() for item in steps):
        raise RecipeRequestError("Генератор вернул некорректные шаги рецепта.")
    if any(
        item.duration_minutes is not None
        and (
            isinstance(item.duration_minutes, bool)
            or not isinstance(item.duration_minutes, int)
            or not 1 <= item.duration_minutes <= 1440
        )
        for item in steps
    ):
        raise RecipeRequestError("Генератор вернул некорректное время шага.")

    try:
        result = check_ingredients([item.name for item in ingredients], command.exclusions)
    except Exception as error:
        raise RecipeSafetyCheckError(
            "Не удалось проверить ингредиенты. Рецепт не показан; попробуйте ещё раз."
        ) from error
    if not result.allowed:
        raise RecipeRequestError(result.reason or "Рецепт не прошёл проверку.")
    if contains_excluded_name(draft.title, command.exclusions) or any(
        contains_excluded_name(step.instruction, command.exclusions) for step in steps
    ):
        raise RecipeRequestError("В шагах найдено упоминание пищевого исключения.")
    listed_ingredients = {
        canonical_name(item.name) or normalize_ingredient_name(item.name)
        for item in ingredients
    }
    unlisted_mentions = mentioned_known_ingredients(
        " ".join([draft.title, *(step.instruction for step in steps)])
    ) - listed_ingredients
    if unlisted_mentions:
        raise RecipeRequestError(
            "В названии или шагах упомянут продукт, которого нет в списке ингредиентов."
        )
    if command.mode == "from_products":
        inventory = {
            canonical_name(item) or normalize_ingredient_name(item)
            for item in products
            if normalize_ingredient_name(item)
        }
        outside_inventory = [
            item.name
            for item in ingredients
            if (canonical_name(item.name) or normalize_ingredient_name(item.name)) not in inventory
        ]
        if outside_inventory:
            raise RecipeRequestError("В рецепте появились продукты, которых нет в вашем списке.")

    return GeneratedRecipe(
        title=draft.title.strip(),
        ingredients=ingredients,
        preparation_time_minutes=draft.preparation_time_minutes,
        steps=[RecipeStep(step.instruction.strip(), step.duration_minutes) for step in steps],
        missing_products=[item.strip() for item in draft.missing_products],
    )
