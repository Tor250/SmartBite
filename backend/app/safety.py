"""Deterministic, conservative checks for the first SmartBite slice.

This small lexicon is a technical seed, not a complete allergen database or
medical source. Extend it only with reviewed aliases and keep the user warning.
"""
from dataclasses import dataclass
import re
import unicodedata

# Only explicit spelling variants are grouped here. This does not infer hidden
# ingredients, product derivatives, cross-contamination, or medical suitability.
ALIASES: dict[str, set[str]] = {
    "молоко": {"молоко", "молока", "молоком", "молоке", "коровье молоко", "молочный продукт"},
    "яйцо": {"яйцо", "яйца", "яйцом", "яйцами", "куриное яйцо", "яичный продукт"},
    "пшеница": {"пшеница", "пшеницы", "пшеницу", "пшеничная мука", "пшеничной муки", "мука пшеничная"},
    "арахис": {"арахис", "арахиса", "арахисом", "арахисе", "земляной орех"},
    "соя": {"соя", "сои", "сою", "соей", "соевые бобы", "соевых бобов"},
    "кунжут": {"кунжут", "кунжута", "кунжутом", "семена кунжута", "семенами кунжута"},
    "рыба": {"рыба", "рыбы", "рыбу", "рыбой", "рыбное филе", "рыбного филе"},
    "креветка": {"креветка", "креветки", "креветок", "креветкой", "креветками"},
    "рис": {"рис", "риса", "рисом", "рисе", "рисовая крупа", "рисовой крупы"},
    "томат": {
        "томат", "томата", "томаты", "томатами", "помидор", "помидора", "помидоры", "помидорами"
    },
    "лук": {"лук", "лука", "луком", "репчатый лук", "репчатым луком"},
    "картофель": {"картофель", "картофеля", "картофелем", "картошка", "картошки", "картошку", "картошкой"},
    "курица": {
        "курица", "курицы", "курицу", "курицей", "куриное мясо", "куриного мяса", "куриное филе"
    },
    "гречка": {"гречка", "гречки", "гречку", "гречкой", "гречневая крупа", "гречневой крупы"},
    "соль": {"соль", "соли", "солью"},
    "вода": {"вода", "воды", "воду", "водой"},
}

def normalize_ingredient_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[^\w\s-]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


_ALIAS_TO_CANONICAL = {
    normalize_ingredient_name(alias): canonical
    for canonical, aliases in ALIASES.items()
    for alias in aliases
}
_AMBIGUOUS_MARKERS = (" или ", "по выбору", "смешанный состав", "неизвестный состав")


def canonical_name(value: str) -> str | None:
    normalized = normalize_ingredient_name(value)
    return _ALIAS_TO_CANONICAL.get(normalized)


def mentioned_known_ingredients(text: str) -> set[str]:
    """Find lexicon ingredients explicitly named in free text.

    This detects omissions from a recipe's structured ingredient list; it does
    not infer unlisted inflections, hidden ingredients or names outside the lexicon.
    """
    normalized_text = normalize_ingredient_name(text)
    found: set[str] = set()
    for canonical, variants in ALIASES.items():
        for variant in variants:
            normalized_variant = normalize_ingredient_name(variant)
            if not normalized_variant:
                continue
            phrase = r"\s+".join(re.escape(word) for word in normalized_variant.split())
            if re.search(rf"(?<!\w){phrase}(?!\w)", normalized_text):
                found.add(canonical)
                break
    return found


def contains_excluded_name(text: str, exclusions: list[str]) -> bool:
    """Catch an explicitly named exclusion in free-text preparation steps."""
    normalized_text = normalize_ingredient_name(text)
    for exclusion in exclusions:
        canonical = canonical_name(exclusion)
        variants = ALIASES[canonical] if canonical else {exclusion}
        for variant in variants:
            normalized_variant = normalize_ingredient_name(variant)
            if not normalized_variant:
                continue
            phrase = r"\s+".join(re.escape(word) for word in normalized_variant.split())
            if re.search(rf"(?<!\w){phrase}(?!\w)", normalized_text):
                return True
    return False


@dataclass(frozen=True)
class CheckResult:
    allowed: bool
    reason: str | None = None


def check_ingredients(ingredients: list[str], exclusions: list[str]) -> CheckResult:
    """Return allowed only when every relevant name can be checked.

    Unknown recipe names fail closed when the user has active exclusions.
    Unknown exclusion names are compared literally; the lexicon cannot infer
    related ingredients or medical cross-reactivity.
    """
    if not ingredients:
        return CheckResult(False, "В рецепте нет списка ингредиентов.")

    unknown_exclusions = [item for item in exclusions if normalize_ingredient_name(item) and canonical_name(item) is None]
    if unknown_exclusions:
        return CheckResult(
            False,
            "Одно из исключений пока не поддерживается словарём проверки.",
        )

    normalized_exclusions = {normalize_ingredient_name(item) for item in exclusions if normalize_ingredient_name(item)}
    canonical_exclusions = {
        canonical_name(item) for item in exclusions if canonical_name(item)
    }

    for item in ingredients:
        normalized = normalize_ingredient_name(item)
        if not normalized:
            return CheckResult(False, "Название одного из ингредиентов не указано.")
        if any(marker in f" {normalized} " for marker in _AMBIGUOUS_MARKERS) or "/" in item:
            return CheckResult(False, f"Не удалось однозначно проверить ингредиент: {item}.")

        canonical = canonical_name(item)
        if normalized in normalized_exclusions or (canonical and canonical in canonical_exclusions):
            return CheckResult(False, f"В рецепте найдено пищевое исключение: {item}.")
        if exclusions and canonical is None:
            return CheckResult(False, f"Ингредиент не распознан словарём проверки: {item}.")

    return CheckResult(True)
