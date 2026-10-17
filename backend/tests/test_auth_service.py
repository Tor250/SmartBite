from datetime import timedelta

from sqlalchemy import select

from app.auth_service import (
    hash_password,
    login_user,
    register_user,
    resolve_session,
    revoke_session,
    token_digest,
    verify_password,
)
from app.models import LoginSession, User, utc_now


def test_register_normalizes_email_and_creates_empty_profile(db_session):
    result = register_user(db_session, "  Student@Example.org ", "strong-pass-123")

    assert result.user.email == "student@example.org"
    assert result.user.profile.preferences == []
    assert result.user.profile.exclusions == []
    assert result.access_token


def test_password_is_stored_as_salted_hash_not_plain_text(db_session):
    result = register_user(db_session, "student@example.org", "strong-pass-123")

    assert result.user.password_hash != "strong-pass-123"
    assert result.user.password_salt
    assert verify_password("strong-pass-123", result.user.password_salt, result.user.password_hash)
    assert not verify_password("wrong-password", result.user.password_salt, result.user.password_hash)


def test_password_verification_rejects_malformed_salt():
    assert not verify_password("any-password", "not-hex", "some-hash")


def test_password_hash_uses_distinct_random_salts():
    first_salt, first_hash = hash_password("strong-pass-123")
    second_salt, second_hash = hash_password("strong-pass-123")

    assert first_salt != second_salt
    assert first_hash != second_hash


def test_registration_rejects_duplicate_email_case_insensitively(db_session):
    register_user(db_session, "student@example.org", "strong-pass-123")

    try:
        register_user(db_session, "STUDENT@example.org", "another-pass-123")
    except ValueError as error:
        assert "уже существует" in str(error)
    else:
        raise AssertionError("Expected duplicate registration to be rejected")


def test_registration_rejects_short_password(db_session):
    try:
        register_user(db_session, "student@example.org", "short")
    except ValueError as error:
        assert "8" in str(error)
    else:
        raise AssertionError("Expected short password to be rejected")


def test_registration_rejects_invalid_email(db_session):
    try:
        register_user(db_session, "not-an-email", "strong-pass-123")
    except ValueError as error:
        assert "корректный адрес" in str(error)
    else:
        raise AssertionError("Expected invalid email to be rejected")


def test_login_issues_token_and_stores_only_digest(db_session):
    register_user(db_session, "student@example.org", "strong-pass-123")

    result = login_user(db_session, "STUDENT@example.org", "strong-pass-123")
    stored = db_session.scalar(select(LoginSession).where(LoginSession.user_id == result.user.id).order_by(LoginSession.id.desc()))

    assert result.access_token
    assert stored is not None
    assert stored.token_hash == token_digest(result.access_token)
    assert stored.token_hash != result.access_token


def test_login_rejects_wrong_password(db_session):
    register_user(db_session, "student@example.org", "strong-pass-123")

    try:
        login_user(db_session, "student@example.org", "wrong-password")
    except ValueError as error:
        assert "Неверный адрес или пароль" in str(error)
    else:
        raise AssertionError("Expected invalid credentials to be rejected")


def test_session_resolves_until_revoked(db_session):
    result = register_user(db_session, "student@example.org", "strong-pass-123")

    assert resolve_session(db_session, result.access_token).id == result.user.id
    revoke_session(db_session, result.access_token)
    assert resolve_session(db_session, result.access_token) is None


def test_expired_session_is_rejected_and_removed(db_session):
    result = register_user(db_session, "student@example.org", "strong-pass-123")
    stored = db_session.scalar(select(LoginSession))
    stored.expires_at = utc_now() - timedelta(seconds=1)
    db_session.commit()

    assert resolve_session(db_session, result.access_token) is None
    assert db_session.scalar(select(LoginSession)) is None


def test_deleting_user_cascades_to_profile_and_sessions(db_session):
    result = register_user(db_session, "student@example.org", "strong-pass-123")

    db_session.delete(result.user)
    db_session.commit()

    assert db_session.scalar(select(User)) is None
    assert db_session.scalar(select(LoginSession)) is None
