import json

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def _alembic_config(database_url: str) -> Config:
    config = Config("alembic.ini")
    # fileConfig() из Alembic заменил бы глобальные обработчики журналирования pytest.
    config.attributes["configure_logger"] = False
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_normalization_migration_preserves_existing_data(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = _alembic_config(database_url)
    command.upgrade(config, "c4b92e6f78ad")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO users (id, email, password_salt, password_hash, created_at)
                VALUES (1, 'migration@example.test', 'salt', 'hash', '2026-10-12 12:00:00')
            """)
        )
        connection.execute(
            text("""
                INSERT INTO profiles (id, user_id, preferences, exclusions)
                VALUES (1, 1, :preferences, :exclusions)
            """),
            {"preferences": json.dumps(["вегетарианское", "острое"]), "exclusions": json.dumps(["арахис"])},
        )
        connection.execute(
            text("""
                INSERT INTO recipes (
                    id, user_id, mode, is_saved, input_products, description, title,
                    ingredients, preparation_time_minutes, steps, missing_products, created_at
                ) VALUES (
                    1, 1, 'from_products', 1, :input_products, NULL, 'Суп', :ingredients,
                    NULL, :steps, :missing_products, '2026-10-12 12:00:00'
                )
            """),
            {
                "input_products": json.dumps(["картофель", "морковь"]),
                "ingredients": json.dumps([
                    {"name": "картофель", "quantity": "2 шт."},
                    {"name": "морковь", "quantity": "1 шт."},
                    "соль",
                ]),
                "steps": json.dumps([
                    {"instruction": "Нарезать овощи.", "duration_minutes": 5},
                    {"instruction": "Сварить суп.", "duration_minutes": 20},
                    "Добавить соль.",
                ]),
                "missing_products": json.dumps(["укроп"]),
            },
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT kind, position, value FROM profile_settings ORDER BY kind, position")
        ).all() == [
            ("exclusion", 0, "арахис"),
            ("preference", 0, "вегетарианское"),
            ("preference", 1, "острое"),
        ]
        assert connection.execute(
            text("SELECT position, name FROM recipe_input_products ORDER BY position")
        ).all() == [(0, "картофель"), (1, "морковь")]
        assert connection.execute(
            text("SELECT position, name, quantity FROM recipe_ingredients ORDER BY position")
        ).all() == [(0, "картофель", "2 шт."), (1, "морковь", "1 шт."), (2, "соль", None)]
        assert connection.execute(
            text("SELECT position, instruction, duration_minutes FROM recipe_steps ORDER BY position")
        ).all() == [
            (0, "Нарезать овощи.", 5),
            (1, "Сварить суп.", 20),
            (2, "Добавить соль.", None),
        ]
        assert connection.execute(
            text("SELECT position, name FROM recipe_missing_products ORDER BY position")
        ).all() == [(0, "укроп")]
        assert "preferences" not in {column["name"] for column in inspect(connection).get_columns("profiles")}
        assert "ingredients" not in {column["name"] for column in inspect(connection).get_columns("recipes")}
        assert "share_token" in {column["name"] for column in inspect(connection).get_columns("recipes")}
        assert {"liked", "review"} <= {
            column["name"] for column in inspect(connection).get_columns("recipe_ratings")
        }
        recipe_columns = {column["name"] for column in inspect(connection).get_columns("recipes")}
        assert {"requested_difficulty", "request_context", "parent_recipe_id"} <= recipe_columns
        assert {"recipe_equipment"} <= set(inspect(connection).get_table_names())
    engine.dispose()


def test_normalization_downgrade_rebuilds_json_lists(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'downgrade.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id, email, password_salt, password_hash, created_at) VALUES (1, 'back@example.test', 's', 'h', '2026-10-12 12:00:00')")
        )
        connection.execute(text("INSERT INTO profiles (id, user_id) VALUES (1, 1)"))
        connection.execute(text("INSERT INTO profile_settings VALUES (1, 'preference', 0, 'без мяса')"))
        connection.execute(text("INSERT INTO recipes (id, user_id, mode, is_saved, description, title, preparation_time_minutes, created_at) VALUES (1, 1, 'from_products', 0, NULL, 'Омлет', NULL, '2026-10-12 12:00:00')"))
        connection.execute(text("INSERT INTO recipe_ingredients VALUES (1, 0, 'яйцо', '2 шт.')"))
        connection.execute(text("INSERT INTO recipe_steps VALUES (1, 0, 'Взбить яйца.', 2)"))
    engine.dispose()

    command.downgrade(config, "c4b92e6f78ad")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        profile = connection.execute(text("SELECT preferences, exclusions FROM profiles WHERE id = 1")).one()
        assert json.loads(profile.preferences) == ["без мяса"]
        assert json.loads(profile.exclusions) == []
        recipe = connection.execute(text("SELECT ingredients, steps, input_products FROM recipes WHERE id = 1")).one()
        assert json.loads(recipe.ingredients) == [{"name": "яйцо", "quantity": "2 шт."}]
        assert json.loads(recipe.steps) == [{"instruction": "Взбить яйца.", "duration_minutes": 2}]
        assert json.loads(recipe.input_products) == []
    engine.dispose()
