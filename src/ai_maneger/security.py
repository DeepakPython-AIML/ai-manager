"""Authentication, password hashing and role-based access control."""
import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import User, get_session, now

# Permission matrix. Authorisation is enforced server-side on every route.
PERMISSIONS: dict[str, set[str]] = {
    "admin": {"read", "run", "approve", "manage_agents", "manage_tenant", "audit"},
    "operator": {"read", "run", "manage_agents"},
    "approver": {"read", "approve", "audit"},
    "viewer": {"read"},
}


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    email: str
    name: str
    role: str

    def can(self, perm: str) -> bool:
        return perm in PERMISSIONS.get(self.role, set())


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt_hex, _, digest_hex = stored.partition("$")
    candidate = hash_password(password, bytes.fromhex(salt_hex)).partition("$")[2]
    return hmac.compare_digest(candidate, digest_hex)


def issue_token(user: User) -> str:
    s = get_settings()
    claims = {
        "sub": user.id,
        "tenant_id": user.tenant_id,
        "role": user.role,
        "email": user.email,
        "name": user.name,
        "exp": now() + timedelta(minutes=s.jwt_ttl_minutes),
    }
    return jwt.encode(claims, s.jwt_secret.get_secret_value(), algorithm="HS256")


@lru_cache
def _jwks() -> jwt.PyJWKClient:
    s = get_settings()
    return jwt.PyJWKClient(
        f"https://cognito-idp.{s.cognito_region}.amazonaws.com/{s.cognito_user_pool_id}/.well-known/jwks.json"
    )


def _decode(token: str) -> Principal:
    s = get_settings()
    if s.auth_mode == "cognito":
        # tenant comes from the custom:tenant_id attribute (admin-controlled, immutable to the user);
        # role from the highest-privilege Cognito group.
        key = _jwks().get_signing_key_from_jwt(token).key
        c = jwt.decode(
            token, key, algorithms=["RS256"], audience=s.cognito_client_id,
            issuer=f"https://cognito-idp.{s.cognito_region}.amazonaws.com/{s.cognito_user_pool_id}",
        )
        groups = c.get("cognito:groups", [])
        role = next((r for r in PERMISSIONS if r in groups), "viewer")
        return Principal(c["sub"], c["custom:tenant_id"], c.get("email", ""), c.get("name", ""), role)
    c = jwt.decode(token, s.jwt_secret.get_secret_value(), algorithms=["HS256"])
    return Principal(c["sub"], c["tenant_id"], c["email"], c["name"], c["role"])


async def current_principal(
    authorization: str | None = Header(default=None), session: AsyncSession = Depends(get_session)
) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    try:
        p = _decode(authorization[7:])
    except (jwt.PyJWTError, KeyError):
        raise HTTPException(401, "Invalid or expired token") from None
    if get_settings().auth_mode == "local":
        # Re-read the user so role changes / removals take effect immediately.
        user = await session.get(User, p.user_id)
        if not user or user.tenant_id != p.tenant_id:
            raise HTTPException(401, "Unknown user")
        p = Principal(user.id, user.tenant_id, user.email, user.name, user.role)
    return p


def require(perm: str):
    async def dep(p: Principal = Depends(current_principal)) -> Principal:
        if not p.can(perm):
            raise HTTPException(403, f"Role '{p.role}' lacks '{perm}' permission")
        return p

    return dep
