from uuid import uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.database import engine
from app.models import Profile, ProfileSetting, Recipe, RecipeIngredientRow, RecipeStepRow, User


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="Requires the PostgreSQL CI service")
def test_postgres_round_trips_normalized_recipe_and_profile_rows():
    inspector = inspect(engine)
    assert {"profile_settings", "recipe_input_products", "recipe_ingredients", "recipe_steps", "recipe_missing_products", "recipe_equipment"}.issubset(
        set(inspector.get_table_names())
    )
    assert "preferences" not in {column["name"] for column in inspector.get_columns("profiles")}
    assert "ingredients" not in {column["name"] for column in inspector.get_columns("recipes")}

    user_id = None
    with Session(engine) as session:
        try:
            user = User(
                email=f"postgres-{uuid4().hex}@example.test",
                password_salt="test-salt",
                password_hash="test-hash",
                profile=Profile(
                    settings=[
                        ProfileSetting(kind="preference", position=0, value="острое"),
                        ProfileSetting(kind="preference", position=1, value="без мяса"),
                        ProfileSetting(kind="exclusion", position=0, value="арахис"),
                    ]
                ),
            )
            session.add(user)
            session.flush()
            user_id = user.id

            recipe = Recipe(
                user_id=user.id,
                mode="from_products",
                is_saved=False,
                input_products=["рис", "томат"],
                description=None,
                title="Рис с томатами",
                ingredients=[
                    {"name": "рис", "quantity": "100 г"},
                    {"name": "томат", "quantity": "1 шт."},
                ],
                preparation_time_minutes=None,
                steps=[
                    {"instruction": "Промойте рис.", "duration_minutes": 2},
                    {"instruction": "Приготовьте с томатами.", "duration_minutes": 18},
                ],
                missing_products=[],
                requested_difficulty=4,
                request_context="Готовлю без духовки.",
                equipment=["Микроволновка"],
            )
            session.add(recipe)
            session.commit()
            recipe_id = recipe.id

            session.expire_all()
            stored = session.get(Recipe, recipe_id)
            assert stored is not None
            assert stored.preparation_time_minutes is None
            assert stored.input_products == ["рис", "томат"]
            assert stored.ingredients[0] == {"name": "рис", "quantity": "100 г"}
            assert stored.steps[1] == {"instruction": "Приготовьте с томатами.", "duration_minutes": 18}
            assert stored.missing_products == []
            assert stored.requested_difficulty == 4
            assert stored.request_context == "Готовлю без духовки."
            assert stored.equipment == ["Микроволновка"]
            assert session.query(RecipeIngredientRow).filter_by(recipe_id=recipe_id).count() == 2
            assert session.query(RecipeStepRow).filter_by(recipe_id=recipe_id).count() == 2
            persisted_user = session.get(User, user_id)
            assert persisted_user is not None
            assert persisted_user.profile.preferences == ["острое", "без мяса"]
            assert persisted_user.profile.exclusions == ["арахис"]
            assert session.query(ProfileSetting).filter_by(profile_id=persisted_user.profile.id).count() == 3
        finally:
            session.rollback()
            if user_id is not None:
                persisted_user = session.get(User, user_id)
                if persisted_user is not None:
                    session.delete(persisted_user)
                    session.commit()
