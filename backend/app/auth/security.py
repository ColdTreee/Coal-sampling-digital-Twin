import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import Role, User, user_roles

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$" + base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(digest).decode()


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt_text, digest_text = encoded.split("$")
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_token(user: User, roles: list[str]) -> str:
    encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    header = encode(b'{"alg":"HS256","typ":"JWT"}')
    payload = encode(json.dumps({
        "sub": str(user.id), "roles": roles, "exp": int(time.time()) + 3600,
    }, separators=(",", ":")).encode())
    content = f"{header}.{payload}"
    signature = hmac.new(get_settings().jwt_secret.encode(), content.encode(), hashlib.sha256).digest()
    return f"{content}.{encode(signature)}"


def decode_token(token: str) -> dict:
    try:
        header, payload, signature = token.split(".")
        content = f"{header}.{payload}"
        expected = hmac.new(get_settings().jwt_secret.encode(), content.encode(), hashlib.sha256).digest()
        decode = lambda value: base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        if not hmac.compare_digest(expected, decode(signature)):
            raise ValueError
        claims = json.loads(decode(payload))
        if claims["exp"] <= time.time():
            raise ValueError
        return claims
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise HTTPException(401, "登录凭证无效或已过期", headers={"WWW-Authenticate": "Bearer"})


@dataclass
class AuthenticatedUser:
    user: User
    roles: set[str]


def current_user(token: str = Depends(oauth2), session: Session = Depends(get_db)) -> AuthenticatedUser:
    claims = decode_token(token)
    try:
        identifier = UUID(claims["sub"])
    except (ValueError, TypeError):
        raise HTTPException(401, "登录凭证无效")
    user = session.get(User, identifier)
    if user is None or not user.is_active:
        raise HTTPException(401, "账号已停用")
    roles = set(session.scalars(
        select(Role.name).join(user_roles, Role.id == user_roles.c.role_id)
        .where(user_roles.c.user_id == user.id)
    ))
    return AuthenticatedUser(user, roles)


def require_roles(*allowed: str):
    def dependency(identity: AuthenticatedUser = Depends(current_user)) -> AuthenticatedUser:
        if not identity.roles.intersection(allowed):
            raise HTTPException(403, "当前角色无权执行此操作")
        return identity
    return dependency
