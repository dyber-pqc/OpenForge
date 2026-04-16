"""Simple JWT-ish auth for the OpenForge API.

Not production grade — passwords are pbkdf2-sha256 hashed to a local JSON
file, tokens are random-url-safe strings stored in-memory. Swap in a real
identity provider before going to prod.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False)

USERS_FILE = Path.home() / ".openforge" / "users.json"
TOKEN_TTL_HOURS = 24
PBKDF2_ITERATIONS = 100_000


# ---------------------------------------------------------------- persistence
def _load_users() -> dict:
    if USERS_FILE.exists():
        try:
            return json.loads(USERS_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load users file: %s", exc)
            return {}
    return {}


def _save_users(users: dict) -> None:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- hashing
def _hash_password(pw: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", pw.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    ).hex()


def _constant_time_eq(a: str, b: str) -> bool:
    return secrets.compare_digest(a, b)


# ---------------------------------------------------------------- user ops
def create_user(username: str, password: str, email: str | None = None) -> dict:
    """Create a new user. Raises ValueError if username is taken."""
    if not username or not password:
        raise ValueError("username and password required")
    users = _load_users()
    if username in users:
        raise ValueError("Username exists")
    salt = secrets.token_hex(16)
    users[username] = {
        "username": username,
        "email": email,
        "salt": salt,
        "password_hash": _hash_password(password, salt),
        "created_at": datetime.utcnow().isoformat(),
        "roles": ["user"],
    }
    _save_users(users)
    logger.info("User created: %s", username)
    return {"username": username, "email": email, "roles": ["user"]}


def verify_user(username: str, password: str) -> bool:
    """Return True if the credentials are valid."""
    users = _load_users()
    user = users.get(username)
    if not user:
        return False
    computed = _hash_password(password, user["salt"])
    return _constant_time_eq(computed, user["password_hash"])


def delete_user(username: str) -> bool:
    users = _load_users()
    if username in users:
        del users[username]
        _save_users(users)
        return True
    return False


def list_users() -> list[dict]:
    users = _load_users()
    return [
        {"username": u["username"], "email": u.get("email"), "roles": u.get("roles", [])}
        for u in users.values()
    ]


# ---------------------------------------------------------------- token store
_active_tokens: dict[str, dict] = {}


def create_token(username: str) -> str:
    """Issue a new token for the given user."""
    token = secrets.token_urlsafe(32)
    _active_tokens[token] = {
        "username": username,
        "issued": datetime.utcnow(),
        "expires": datetime.utcnow() + timedelta(hours=TOKEN_TTL_HOURS),
    }
    return token


def verify_token(token: str) -> Optional[str]:
    """Return the username associated with a valid token, else None."""
    info = _active_tokens.get(token)
    if not info:
        return None
    if info["expires"] < datetime.utcnow():
        _active_tokens.pop(token, None)
        return None
    return info["username"]


def revoke_token(token: str) -> bool:
    return _active_tokens.pop(token, None) is not None


def cleanup_expired_tokens() -> int:
    now = datetime.utcnow()
    expired = [t for t, info in _active_tokens.items() if info["expires"] < now]
    for t in expired:
        _active_tokens.pop(t, None)
    return len(expired)


# ---------------------------------------------------------------- deps
async def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> str:
    """FastAPI dependency that resolves the current authenticated user."""
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = verify_token(token)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username


async def get_optional_user(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[str]:
    if token is None:
        return None
    return verify_token(token)


# ---------------------------------------------------------------- schema
class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class UserInfo(BaseModel):
    username: str
    email: Optional[str] = None
    roles: list[str] = []


# ---------------------------------------------------------------- router
router = APIRouter()


@router.post("/auth/register", response_model=UserInfo)
async def register(req: RegisterRequest) -> UserInfo:
    """Create a new user account."""
    try:
        info = create_user(req.username, req.password, req.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return UserInfo(**info)


@router.post("/auth/token", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends()) -> TokenResponse:
    """OAuth2-style password grant."""
    if not verify_user(form.username, form.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_token(form.username)
    return TokenResponse(access_token=token, username=form.username)


@router.post("/auth/logout")
async def logout(token: str = Depends(oauth2_scheme)) -> dict:
    if token:
        revoke_token(token)
    return {"ok": True}


@router.get("/auth/me", response_model=UserInfo)
async def me(username: str = Depends(get_current_user)) -> UserInfo:
    users = _load_users()
    user = users.get(username, {})
    return UserInfo(
        username=username,
        email=user.get("email"),
        roles=user.get("roles", ["user"]),
    )
