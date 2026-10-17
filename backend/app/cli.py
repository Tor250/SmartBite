"""Small console adapter that calls the same use case as the HTTP API."""
import argparse
from dataclasses import asdict
import json
import sys
from collections.abc import Sequence

from .application.recipes import GenerateRecipeCommand, RecipeRequestError, generate_recipe
from .generator import DemoRecipeGenerator, RecipeGenerator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Демонстрационный генератор рецептов SmartBite")
    parser.add_argument("--mode", choices=("from_products", "preferences"), default="from_products")
    parser.add_argument("--products", nargs="*", default=[], help="Продукты, которые есть дома")
    parser.add_argument("--preferences", nargs="*", default=[], help="Пищевые предпочтения")
    parser.add_argument("--exclusions", nargs="*", default=[], help="Исключения из профиля")
    parser.add_argument("--description", help="Пожелания к рецепту")
    return parser


def run(argv: Sequence[str] | None = None, generator: RecipeGenerator | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = GenerateRecipeCommand(
        mode=args.mode,
        products=args.products,
        description=args.description,
        preferences=args.preferences,
        exclusions=args.exclusions,
    )
    try:
        recipe = generate_recipe(command, generator or DemoRecipeGenerator())
    except RecipeRequestError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "generator": "demo",
                "title": recipe.title,
                "ingredients": [asdict(item) for item in recipe.ingredients],
                "preparation_time_minutes": recipe.preparation_time_minutes,
                "steps": [asdict(item) for item in recipe.steps],
                "missing_products": recipe.missing_products,
                "warning": "Демо-результат. Проверка не является медицинской гарантией.",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
