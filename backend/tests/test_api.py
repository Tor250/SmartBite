
import pytest

from app import main
from app.application import recipes as recipe_application
from app.generation_runner import GenerationBusy, GenerationTimedOut


def register(client, email="cook@example.org", password="strong-pass-123"):
    response = client.post("/api/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201
    return response.json()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_profile_requires_login(api_client):
    response = api_client.get("/api/profile")

    assert response.status_code == 401


def test_health_endpoint_reports_api_ready(api_client):
    response = api_client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_analytics_is_private_and_shows_aggregated_recipe_feedback(api_client, db_session, monkeypatch):
    from app.models import Recipe, RecipeRating

    account = register(api_client, "admin@example.org")
    other = register(api_client, "cook2@example.org")
    recipe = Recipe(user_id=other["user_id"], mode="preferences", title="Суп с чечевицей")
    db_session.add(recipe)
    db_session.flush()
    db_session.add(RecipeRating(user_id=other["user_id"], recipe_id=recipe.id, liked=True, suitable=True))
    db_session.commit()

    monkeypatch.setenv("SMARTBITE_ADMIN_EMAILS", "admin@example.org")
    response = api_client.get("/api/admin/analytics", headers=auth(account["access_token"]))
    forbidden = api_client.get("/api/admin/analytics", headers=auth(other["access_token"]))

    assert forbidden.status_code == 403
    assert response.status_code == 200
    assert response.json()["users_total"] == 2
    assert response.json()["recipes_total"] == 1
    assert response.json()["likes_total"] == 1
    assert response.json()["popular_recipes"] == [
        {"title": "Суп с чечевицей", "ratings": 1, "likes": 1, "suitable": 1}
    ]
    assert "email" not in response.text


def test_registration_rejects_duplicate_account_and_short_password(api_client):
    register(api_client, "same@example.org")

    duplicate = api_client.post(
        "/api/auth/register",
        json={"email": "SAME@example.org", "password": "another-pass-123"},
    )
    short_password = api_client.post(
        "/api/auth/register",
        json={"email": "new@example.org", "password": "short"},
    )

    assert duplicate.status_code == 409
    assert short_password.status_code == 422


def test_login_returns_session_and_rejects_wrong_password(api_client):
    register(api_client, "login@example.org")

    valid = api_client.post(
        "/api/auth/login",
        json={"email": "LOGIN@example.org", "password": "strong-pass-123"},
    )
    invalid = api_client.post(
        "/api/auth/login",
        json={"email": "login@example.org", "password": "wrong-password"},
    )

    assert valid.status_code == 200
    assert valid.json()["access_token"]
    assert invalid.status_code == 401


def test_registration_then_profile_update_and_readback(api_client):
    account = register(api_client, "cook@example.org")
    headers = auth(account["access_token"])

    before = api_client.get("/api/profile", headers=headers)
    updated = api_client.put(
        "/api/profile",
        headers=headers,
        json={"preferences": ["  без жарки  "], "exclusions": ["молоко", ""]},
    )
    after = api_client.get("/api/profile", headers=headers)
    replaced = api_client.put(
        "/api/profile",
        headers=headers,
        json={"preferences": ["острое", "вегетарианское"], "exclusions": ["арахис"]},
    )
    after_replacement = api_client.get("/api/profile", headers=headers)

    assert before.json()["preferences"] == []
    assert updated.status_code == 200
    assert after.json()["preferences"] == ["без жарки"]
    assert after.json()["exclusions"] == ["молоко"]
    assert replaced.status_code == 200
    assert after_replacement.json()["preferences"] == ["острое", "вегетарианское"]
    assert after_replacement.json()["exclusions"] == ["арахис"]


def test_profile_update_recreates_missing_profile(api_client, db_session):
    from sqlalchemy import select
    from app.models import User

    account = register(api_client)
    user = db_session.scalar(select(User).where(User.id == account["user_id"]))
    db_session.delete(user.profile)
    db_session.commit()
    db_session.expire(user, ["profile"])

    response = api_client.put(
        "/api/profile",
        headers=auth(account["access_token"]),
        json={"preferences": ["без жарки"], "exclusions": ["арахис"]},
    )

    assert response.status_code == 200
    assert response.json()["preferences"] == ["без жарки"]
    assert response.json()["exclusions"] == ["арахис"]


def test_profile_rejects_too_long_item(api_client):
    account = register(api_client)

    response = api_client.put(
        "/api/profile",
        headers=auth(account["access_token"]),
        json={"preferences": ["а" * 101], "exclusions": []},
    )

    assert response.status_code == 422


def test_recipe_generation_uses_saved_profile_exclusions(api_client):
    account = register(api_client)
    headers = auth(account["access_token"])
    api_client.put("/api/profile", headers=headers, json={"preferences": [], "exclusions": ["рис"]})

    response = api_client.post(
        "/api/recipes/generate",
        headers=headers,
        json={"mode": "from_products", "products": ["рис", "томат"]},
    )

    assert response.status_code == 422
    assert "исключение" in response.json()["detail"]


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (GenerationBusy(), "Сервис генерации занят"),
        (GenerationTimedOut(), "не ответил вовремя"),
    ],
)
def test_account_generation_uses_shared_bounded_runner(api_client, monkeypatch, failure, message):
    account = register(api_client)

    class FailingRunner:
        async def run(self, *_args):
            raise failure

    monkeypatch.setattr(main, "generation_runner", FailingRunner())
    response = api_client.post(
        "/api/recipes/generate",
        headers=auth(account["access_token"]),
        json={"mode": "from_products", "products": ["рис"]},
    )

    assert response.status_code == 503
    assert message in response.json()["detail"]


def test_account_generation_fails_closed_if_safety_check_crashes(api_client, monkeypatch):
    account = register(api_client)

    def failed_check(*_args, **_kwargs):
        raise RuntimeError("internal checker detail")

    monkeypatch.setattr(recipe_application, "check_ingredients", failed_check)
    response = api_client.post(
        "/api/recipes/generate",
        headers=auth(account["access_token"]),
        json={"mode": "from_products", "products": ["рис"]},
    )

    assert response.status_code == 503
    assert "Рецепт не показан" in response.json()["detail"]
    assert "internal checker detail" not in response.text


def test_request_cannot_override_saved_exclusions(api_client):
    account = register(api_client)
    headers = auth(account["access_token"])
    api_client.put("/api/profile", headers=headers, json={"preferences": [], "exclusions": ["рис"]})

    response = api_client.post(
        "/api/recipes/generate",
        headers=headers,
        json={"mode": "from_products", "products": ["рис", "томат"], "exclusions": []},
    )

    assert response.status_code == 422


def test_accounts_cannot_read_each_others_profiles(api_client):
    first = register(api_client, "first@example.org")
    second = register(api_client, "second@example.org")
    api_client.put(
        "/api/profile",
        headers=auth(first["access_token"]),
        json={"preferences": ["острое"], "exclusions": ["арахис"]},
    )

    second_profile = api_client.get("/api/profile", headers=auth(second["access_token"]))

    assert second_profile.json()["preferences"] == []
    assert second_profile.json()["exclusions"] == []


def test_logout_revokes_session(api_client):
    account = register(api_client)
    headers = auth(account["access_token"])

    logout = api_client.post("/api/auth/logout", headers=headers)
    profile = api_client.get("/api/profile", headers=headers)

    assert logout.status_code == 204
    assert profile.status_code == 401


def test_account_deletion_revokes_current_session(api_client):
    account = register(api_client)
    headers = auth(account["access_token"])
    generated = create_recipe(api_client, headers)
    api_client.put(f"/api/recipes/{generated['id']}/save", headers=headers)

    deleted = api_client.delete("/api/account", headers=headers)
    profile = api_client.get("/api/profile", headers=headers)
    book = api_client.get("/api/recipes", headers=headers)

    assert deleted.status_code == 204
    assert profile.status_code == 401
    assert book.status_code == 401


def create_recipe(client, headers):
    response = client.post(
        "/api/recipes/generate",
        headers=headers,
        json={"mode": "from_products", "products": ["рис", "томат"]},
    )
    assert response.status_code == 200
    return response.json()


def test_generated_recipe_is_not_added_to_book_until_user_saves_it(api_client):
    account = register(api_client)
    headers = auth(account["access_token"])

    generated = create_recipe(api_client, headers)
    book = api_client.get("/api/recipes", headers=headers)

    assert generated["is_saved"] is False
    assert book.status_code == 200
    assert book.json() == []


def test_user_can_save_list_open_and_delete_own_recipe(api_client):
    account = register(api_client)
    headers = auth(account["access_token"])
    generated = create_recipe(api_client, headers)

    saved = api_client.put(f"/api/recipes/{generated['id']}/save", headers=headers)
    book = api_client.get("/api/recipes", headers=headers)
    opened = api_client.get(f"/api/recipes/{generated['id']}", headers=headers)
    deleted = api_client.delete(f"/api/recipes/{generated['id']}", headers=headers)
    after_delete = api_client.get("/api/recipes", headers=headers)

    assert saved.status_code == 200 and saved.json()["is_saved"] is True
    assert len(book.json()) == 1
    assert opened.json()["title"] == generated["title"]
    assert deleted.status_code == 204
    assert after_delete.json() == []


def test_user_cannot_save_or_delete_missing_recipe(api_client):
    account = register(api_client)
    headers = auth(account["access_token"])

    save = api_client.put("/api/recipes/99999/save", headers=headers)
    delete = api_client.delete("/api/recipes/99999", headers=headers)

    assert save.status_code == 404
    assert delete.status_code == 404


def test_saved_recipe_is_checked_again_after_profile_exclusions_change(api_client):
    account = register(api_client)
    headers = auth(account["access_token"])
    generated = create_recipe(api_client, headers)
    api_client.put(f"/api/recipes/{generated['id']}/save", headers=headers)
    api_client.put(
        "/api/profile",
        headers=headers,
        json={"preferences": [], "exclusions": ["рис"]},
    )

    opened = api_client.get(f"/api/recipes/{generated['id']}", headers=headers)
    saved = api_client.put(f"/api/recipes/{generated['id']}/save", headers=headers)

    assert opened.status_code == 422
    assert saved.status_code == 422


def test_recipe_and_rating_are_private_to_owner(api_client):
    first = register(api_client, "first@example.org")
    second = register(api_client, "second@example.org")
    first_headers = auth(first["access_token"])
    second_headers = auth(second["access_token"])
    recipe = create_recipe(api_client, first_headers)

    assert api_client.get(f"/api/recipes/{recipe['id']}", headers=second_headers).status_code == 404
    assert api_client.put(
        f"/api/recipes/{recipe['id']}/rating",
        headers=second_headers,
        json={"suitable": True},
    ).status_code == 404


def test_user_can_rate_and_change_rating(api_client):
    account = register(api_client)
    headers = auth(account["access_token"])
    recipe = create_recipe(api_client, headers)

    first = api_client.put(
        f"/api/recipes/{recipe['id']}/rating", headers=headers, json={"suitable": True}
    )
    changed = api_client.put(
        f"/api/recipes/{recipe['id']}/rating", headers=headers, json={"suitable": False}
    )

    assert first.json()["suitable"] is True
    assert changed.json()["suitable"] is False


def test_user_can_add_like_and_review_to_recipe_rating(api_client):
    account = register(api_client)
    headers = auth(account["access_token"])
    recipe = create_recipe(api_client, headers)

    response = api_client.put(
        f"/api/recipes/{recipe['id']}/rating",
        headers=headers,
        json={"liked": True, "review": "Быстро и вкусно"},
    )

    assert response.status_code == 200
    assert response.json()["liked"] is True
    assert response.json()["review"] == "Быстро и вкусно"
    assert response.json()["suitable"] is None


def test_future_generation_uses_rating_signals_but_not_private_review_text(api_client, monkeypatch):
    import json

    from app import main
    from app.generator import StructuredRecipeGenerator

    account = register(api_client)
    headers = auth(account["access_token"])
    previous = create_recipe(api_client, headers)
    api_client.put(
        f"/api/recipes/{previous['id']}/rating",
        headers=headers,
        json={"liked": True, "suitable": True, "review": "Личный комментарий пользователя"},
    )
    captured = {}

    class TasteAdapter:
        def request_json(self, _system_instruction, input_json):
            captured.update(json.loads(input_json))
            return json.dumps({
                "title": "Рис с томатом",
                "preparation_time_minutes": 15,
                "ingredients": [
                    {"name": "рис", "quantity": "100 г"},
                    {"name": "томат", "quantity": "1 шт."},
                ],
                "steps": [{"instruction": "Приготовьте рис с томатом.", "duration_minutes": 15}],
            }, ensure_ascii=False)

    monkeypatch.setattr(main, "generator", StructuredRecipeGenerator(TasteAdapter()))
    generated = api_client.post(
        "/api/recipes/generate",
        headers=headers,
        json={"mode": "from_products", "products": ["рис", "томат"]},
    )

    assert generated.status_code == 200
    assert any(previous["title"] in value for value in captured["preferences"])
    assert all("Личный комментарий пользователя" not in value for value in captured["preferences"])


def test_user_can_read_full_generation_history(api_client):
    account = register(api_client)
    headers = auth(account["access_token"])
    first = create_recipe(api_client, headers)
    second = create_recipe(api_client, headers)

    history = api_client.get("/api/recipes/history", headers=headers)

    assert history.status_code == 200
    assert {item["id"] for item in history.json()} == {first["id"], second["id"]}
    assert api_client.get("/api/recipes").status_code == 401


def test_signed_in_user_can_generate_and_revisit_wishes_mode(api_client, monkeypatch):
    import json

    from app import main
    from app.generator import StructuredRecipeGenerator

    class WishesAdapter:
        def request_json(self, _system_instruction, _input_json):
            return json.dumps({
                "title": "Рис с томатами",
                "preparation_time_minutes": 20,
                "ingredients": [
                    {"name": "рис", "quantity": "100 г"},
                    {"name": "томат", "quantity": "1 шт."},
                ],
                "steps": [{"instruction": "Приготовьте рис с томатом.", "duration_minutes": 20}],
                "missing_products": ["томат"],
            }, ensure_ascii=False)

    monkeypatch.setattr(main, "generator", StructuredRecipeGenerator(WishesAdapter()))
    account = register(api_client)
    headers = auth(account["access_token"])
    api_client.put(
        "/api/profile",
        headers=headers,
        json={"preferences": ["без жарки"], "exclusions": []},
    )

    generated = api_client.post(
        "/api/recipes/generate",
        headers=headers,
        json={"mode": "preferences", "products": ["рис"], "description": "быстрый ужин"},
    )
    history = api_client.get("/api/recipes/history", headers=headers)

    assert generated.status_code == 200
    assert generated.json()["mode"] == "preferences"
    assert generated.json()["missing_products"] == ["томат"]
    assert len(history.json()) == 1
    assert history.json()[0]["mode"] == "preferences"
    assert history.json()[0]["title"] == "Рис с томатами"


def test_signed_in_generation_persists_difficulty_equipment_and_kitchen_context(api_client):
    account = register(api_client)
    headers = auth(account["access_token"])

    generated = api_client.post(
        "/api/recipes/generate",
        headers=headers,
        json={
            "mode": "from_products",
            "products": ["рис", "томат"],
            "difficulty": 2,
            "equipment": ["Микроволновка"],
            "request_context": "Готовлю в общежитии.",
        },
    )
    history = api_client.get("/api/recipes/history", headers=headers)

    assert generated.status_code == 200
    assert generated.json()["difficulty"] == 2
    assert generated.json()["equipment"] == ["Микроволновка"]
    assert generated.json()["request_context"] == "Готовлю в общежитии."
    assert history.json()[0]["equipment"] == ["Микроволновка"]
    assert history.json()[0]["request_context"] == "Готовлю в общежитии."


def test_recipe_refinement_stores_parent_and_preserves_account_isolation(api_client, monkeypatch):
    import json

    from app import main
    from app.generator import StructuredRecipeGenerator

    class RefinementAdapter:
        def request_json(self, _system_instruction, _input_json):
            return json.dumps({
                "title": "Рис с томатами по-новому",
                "preparation_time_minutes": 20,
                "ingredients": [
                    {"name": "рис", "quantity": "100 г"},
                    {"name": "томат", "quantity": "1 шт."},
                ],
                "steps": [{"instruction": "Приготовьте рис с томатами.", "duration_minutes": 20}],
            }, ensure_ascii=False)

    monkeypatch.setattr(main, "generator", StructuredRecipeGenerator(RefinementAdapter()))
    owner = register(api_client, "refine-owner@example.org")
    other = register(api_client, "refine-other@example.org")
    owner_headers = auth(owner["access_token"])
    source = create_recipe(api_client, owner_headers)

    refined = api_client.post(
        f"/api/recipes/{source['id']}/refine",
        headers=owner_headers,
        json={"scope": "replace", "instruction": "Сделай вкус более свежим", "equipment": ["Плита"]},
    )
    forbidden = api_client.post(
        f"/api/recipes/{source['id']}/refine",
        headers=auth(other["access_token"]),
        json={"scope": "adjust", "instruction": "Замени томат"},
    )

    assert refined.status_code == 200
    assert refined.json()["title"] == "Рис с томатами по-новому"
    assert refined.json()["parent_recipe_id"] == source["id"]
    assert refined.json()["equipment"] == ["Плита"]
    assert forbidden.status_code == 404


def test_user_can_share_recipe_by_revocable_public_link(api_client):
    account = register(api_client)
    headers = auth(account["access_token"])
    recipe = create_recipe(api_client, headers)

    shared = api_client.post(f"/api/recipes/{recipe['id']}/share", headers=headers)
    assert shared.status_code == 200
    share_path = shared.json()["share_url"].replace("http://test", "")
    public_recipe = api_client.get(share_path)
    assert public_recipe.status_code == 200
    assert public_recipe.json()["title"] == recipe["title"]
    assert "email" not in public_recipe.json()

    revoked = api_client.delete(f"/api/recipes/{recipe['id']}/share", headers=headers)
    after_revoke = api_client.get(share_path)
    assert revoked.status_code == 204
    assert after_revoke.status_code == 404


def test_user_cannot_share_another_users_recipe(api_client):
    owner = register(api_client, "owner@example.org")
    other = register(api_client, "other@example.org")
    recipe = create_recipe(api_client, auth(owner["access_token"]))

    response = api_client.post(
        f"/api/recipes/{recipe['id']}/share",
        headers=auth(other["access_token"]),
    )

    assert response.status_code == 404


def test_d7_events_store_only_account_id_type_and_timestamp(api_client, db_session):
    from app.models import UsageEvent
    from sqlalchemy import select

    account = register(api_client)
    headers = auth(account["access_token"])
    first_recipe = create_recipe(api_client, headers)
    second_recipe = create_recipe(api_client, headers)
    events = db_session.scalars(select(UsageEvent).order_by(UsageEvent.id)).all()

    assert first_recipe["id"] != second_recipe["id"]
    assert [event.event_type for event in events] == ["recipe_shown_first", "recipe_shown_repeat"]
    assert all(event.user_id == account["user_id"] and event.occurred_at for event in events)
    assert all(not hasattr(event, "products") and not hasattr(event, "description") for event in events)
