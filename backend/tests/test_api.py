
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
