from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import LoginSession, Profile, User

PBKDF2_ROUNDS = 600_000
SESSION_DAYS = 14
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


@dataclass(frozen=True)
class AuthResult:
    user: User
    access_token: str


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, expected_hash: str) -> bool:
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    _, actual_hash = hash_password(password, salt)
    return hmac.compare_digest(actual_hash, expected_hash)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(
        LoginSession(
            user_id=user.id,
            token_hash=token_digest(token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS),
        )
    )
    return token


def register_user(db: Session, email: str, password: str) -> AuthResult:
    normalized_email = email.strip().casefold()
    if len(normalized_email) > 320 or not _EMAIL_RE.fullmatch(normalized_email):
        raise ValueError("Укажите корректный адрес электронной почты.")
    if len(password) < 8 or len(password) > 128:
        raise ValueError("Пароль должен содержать от 8 до 128 символов.")
    if db.scalar(select(User).where(User.email == normalized_email)):
        raise ValueError("Аккаунт с таким адресом уже существует.")

    salt, password_hash = hash_password(password)
    user = User(email=normalized_email, password_salt=salt, password_hash=password_hash)
    user.profile = Profile(preferences=[], exclusions=[])
    db.add(user)
    db.flush()
    token = _new_session(db, user)
    db.commit()
    db.refresh(user)
    return AuthResult(user=user, access_token=token)


def login_user(db: Session, email: str, password: str) -> AuthResult:
    normalized_email = email.strip().casefold()
    user = db.scalar(select(User).where(User.email == normalized_email))
    if user is None or not verify_password(password, user.password_salt, user.password_hash):
        raise ValueError("Неверный адрес или пароль.")
    token = _new_session(db, user)
    db.commit()
    return AuthResult(user=user, access_token=token)


def resolve_session(db: Session, token: str) -> User | None:
    session = db.scalar(select(LoginSession).where(LoginSession.token_hash == token_digest(token)))
    if session is None:
        return None
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        db.delete(session)
        db.commit()
        return None
    return session.user


def revoke_session(db: Session, token: str) -> None:
    session = db.scalar(select(LoginSession).where(LoginSession.token_hash == token_digest(token)))
    if session is not None:
        db.delete(session)
        db.commit()
