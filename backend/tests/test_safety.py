from app.safety import check_ingredients, contains_excluded_name, mentioned_known_ingredients


def test_blocks_exact_excluded_ingredient():
    result = check_ingredients(["рис", "томат"], ["рис"])

    assert result.allowed is False
    assert "исключение" in (result.reason or "")


def test_blocks_supported_spelling_variant_of_exclusion():
    result = check_ingredients(["рисовая крупа"], ["рис"])

    assert result.allowed is False


def test_blocks_inflected_ingredient_name_matching_an_exclusion():
    result = check_ingredients(["молока"], ["молоко"])

    assert result.allowed is False


def test_allows_known_ingredients_when_they_do_not_match_exclusions():
    result = check_ingredients(["рис", "томат"], ["молоко"])

    assert result.allowed is True
    assert result.reason is None


def test_blocks_unknown_recipe_ingredient_when_exclusions_are_active():
    result = check_ingredients(["рис", "чеснок"], ["молоко"])

    assert result.allowed is False
    assert "не распознан" in (result.reason or "")


def test_blocks_exclusion_that_is_not_in_the_supported_lexicon():
    result = check_ingredients(["рис", "томат"], ["глютен"])

    assert result.allowed is False
    assert "не поддерживается" in (result.reason or "")


def test_blocks_ambiguous_ingredient_name():
    result = check_ingredients(["рис или гречка"], [])

    assert result.allowed is False
    assert "однозначно" in (result.reason or "")


def test_blocks_recipe_without_ingredients():
    result = check_ingredients([], [])

    assert result.allowed is False
    assert result.reason == "В рецепте нет списка ингредиентов."


def test_blocks_ingredient_with_blank_name():
    result = check_ingredients(["   "], [])

    assert result.allowed is False
    assert "не указано" in (result.reason or "")


def test_allows_unknown_ingredient_only_when_no_exclusions_are_set():
    result = check_ingredients(["чеснок"], [])

    assert result.allowed is True


def test_finds_explicit_exclusion_in_preparation_text():
    assert contains_excluded_name("Добавьте немного молока и прогрейте смесь.", ["молоко"])


def test_does_not_find_exclusion_inside_an_unrelated_word():
    assert not contains_excluded_name("Подготовьте ингредиенты.", ["молоко"])


def test_finds_known_ingredient_explicitly_mentioned_in_free_text():
    assert mentioned_known_ingredients("Добавьте картофель и курицу.") == {"картофель", "курица"}


def test_does_not_match_ingredient_as_part_of_an_unrelated_word():
    assert mentioned_known_ingredients("Подготовьте ингредиенты.") == set()
