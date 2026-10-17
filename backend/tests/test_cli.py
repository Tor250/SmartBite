import json

from app.cli import run


def test_cli_prints_demo_recipe_as_json(capsys):
    result = run(["--mode", "from_products", "--products", "рис", "томат"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert payload["generator"] == "demo"
    assert [item["name"] for item in payload["ingredients"]] == ["рис", "томат"]
    assert "медицинской гарантией" in payload["warning"]


def test_cli_fails_closed_and_prints_error_to_stderr(capsys):
    result = run(
        ["--mode", "from_products", "--products", "рис", "чеснок", "--exclusions", "молоко"]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert result == 2
    assert "не распознан" in payload["error"]
    assert captured.out == ""
