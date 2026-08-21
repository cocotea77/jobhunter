"""Accounts and ownership: who is asking, and what is theirs.

The design in four sentences. Sign-in is by email link — no passwords
exist anywhere, so none can leak. Sessions are DATABASE ROWS, not signed
cookies, so signing out deletes the row and truly ends the session. The
browser holds only a random token in an httpOnly cookie, and the
database stores only that token's HASH — a stolen database dump contains
nothing a browser can replay. Ownership answers "not found", never
"forbidden": admitting that someone else's data exists is itself a leak.

Why tokens are hashed at rest: the same reason passwords would be. A
row like (user 7, a3f9...) lets an attacker with database access learn
that user 7 has a session — but not present it. The raw token exists in
exactly two places: the user's cookie and, briefly, the sign-in link.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import delete, select

from app.config import settings
from app.db import session_factory
from app.models import AuthSession, Candidate, LoginToken, User


def _hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- sign-in links ----------------------------------------------------------


async def create_login_token(email: str) -> str:
    """Create (or find) the user for this email and mint a one-time,
    short-lived sign-in token. Returns the RAW token — the only moment it
    exists server-side in the clear."""
    email = email.strip().lower()
    raw = secrets.token_urlsafe(32)
    async with session_factory() as db:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is None:
            user = User(email=email)
            db.add(user)
            await db.flush()
        db.add(
            LoginToken(
                user_id=user.id,
                token_hash=_hash(raw),
                expires_at=_now() + timedelta(minutes=settings.login_token_ttl_minutes),
            )
        )
        await db.commit()
    return raw


async def send_login_email(email: str, link: str) -> None:
    """Deliver the sign-in link. Console mode (no key): print it — free,
    offline, classroom-ready. With a Resend key: real email."""
    if not settings.resend_api_key:
        print(f"[login link for {email}] {link}")
        return
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.email_from,
                "to": [email],
                "subject": "Your JobHunter sign-in link",
                "text": (
                    "Click to sign in (valid for "
                    f"{settings.login_token_ttl_minutes} minutes):\n{link}\n\n"
                    "If you did not request this, ignore this email."
                ),
            },
            timeout=10,
        )
        response.raise_for_status()


async def verify_login_token(raw_token: str) -> User:
    """Redeem a sign-in token: it must exist, be unexpired, and be UNUSED
    — and redeeming marks it used, atomically with the check. A link
    works exactly once; forwarded or replayed, it is dead."""
    async with session_factory() as db:
        token = (
            await db.execute(
                select(LoginToken).where(LoginToken.token_hash == _hash(raw_token))
            )
        ).scalar_one_or_none()
        if token is None or token.used_at is not None or token.expires_at < _now():
            # One error for all three reasons: an attacker probing tokens
            # learns nothing about WHICH way a guess was wrong.
            raise HTTPException(status_code=400, detail="invalid or expired sign-in link")
        token.used_at = _now()
        user = await db.get(User, token.user_id)
        await db.commit()
        return user


# --- sessions ---------------------------------------------------------------


async def create_session(user: User) -> str:
    """Start a session; return the raw token destined for the cookie."""
    raw = secrets.token_urlsafe(32)
    async with session_factory() as db:
        db.add(
            AuthSession(
                user_id=user.id,
                token_hash=_hash(raw),
                expires_at=_now() + timedelta(days=settings.session_ttl_days),
            )
        )
        await db.commit()
    return raw


def set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        httponly=True,  # JavaScript cannot read it — theft via script is out
        samesite="lax",  # not sent on cross-site posts — blunts request forgery
        secure=settings.environment != "development",  # HTTPS-only outside dev
        max_age=settings.session_ttl_days * 24 * 3600,
    )


async def end_session(raw_token: str) -> None:
    """Logout = delete the row. Revocation is real, not a client promise."""
    async with session_factory() as db:
        await db.execute(
            delete(AuthSession).where(AuthSession.token_hash == _hash(raw_token))
        )
        await db.commit()


# --- request dependencies ---------------------------------------------------


async def current_user(request: Request) -> User:
    """Who is asking? 401 if we do not know — endpoints that depend on
    this simply cannot run for strangers."""
    raw = request.cookies.get(settings.session_cookie_name)
    if not raw:
        raise HTTPException(status_code=401, detail="sign in required")
    async with session_factory() as db:
        session = (
            await db.execute(
                select(AuthSession).where(AuthSession.token_hash == _hash(raw))
            )
        ).scalar_one_or_none()
        if session is None or session.expires_at < _now():
            raise HTTPException(status_code=401, detail="sign in required")
        user = await db.get(User, session.user_id)
    return user


async def get_owned_candidate(candidate_id: int, user: User) -> Candidate:
    """THE ownership check, in exactly one place. Wrong owner and
    nonexistent are the same answer — 404 — because "forbidden" would
    confirm another person's data exists. Every candidate-scoped endpoint
    goes through here; an endpoint that does not is a bug by definition."""
    async with session_factory() as db:
        candidate = await db.get(Candidate, candidate_id)
    if candidate is None or candidate.user_id != user.id:
        raise HTTPException(status_code=404, detail="candidate not found")
    return candidate


def require_admin(request: Request) -> None:
    """Operator endpoints: a shared token in x-admin-token. And a launch
    safety: production with the development default is refused outright —
    fail early, before the first stranger arrives."""
    if settings.environment == "production" and settings.admin_token == "dev-admin-token":
        raise HTTPException(
            status_code=503,
            detail="operator endpoints disabled: ADMIN_TOKEN still has its "
            "development default in production",
        )
    if request.headers.get("x-admin-token") != settings.admin_token:
        raise HTTPException(status_code=401, detail="admin token required")


CurrentUser = Depends(current_user)
