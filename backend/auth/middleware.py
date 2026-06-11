from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from auth.session import ROLE_ORDER, SESSION_COOKIE, SessionStore
from config import AppConfig

logger = logging.getLogger(__name__)


@dataclass
class CurrentUser:
    email: str
    name: str
    role: str
    access_token: str | None = None


async def _try_refresh(request: Request, session_id: str) -> None:
    """Silently refresh the Cognito access token if it's about to expire.

    Failures are swallowed — a stale token is better than a broken request.
    The session itself remains valid even if the refresh fails.
    """
    store: SessionStore = request.app.state.session_store
    session = await store.get(session_id)
    if not session or not session.access_token_needs_refresh():
        return
    if not session.refresh_token:
        return

    try:
        cognito = request.app.state.cognito_client
        token_set = await cognito.refresh_tokens(session.refresh_token)
        await store.update_tokens(
            session_id,
            access_token=token_set.access_token,
            # Cognito doesn't return a new refresh_token; keep the old one
            refresh_token=token_set.refresh_token,
        )
        logger.info("Silently refreshed Cognito tokens for session %s", session_id[:8])
    except Exception as exc:
        # Log but don't fail the request — user stays logged in with old token
        logger.warning("Token refresh failed for session %s: %s", session_id[:8], exc)


async def get_current_user(request: Request) -> CurrentUser:
    cfg: AppConfig = request.app.state.config
    if not cfg.require_auth:
        return CurrentUser(email=cfg.dev_user_email, name="Dev User", role="super_admin")

    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        raise HTTPException(status_code=401, detail="unauthenticated")

    store: SessionStore = request.app.state.session_store
    session = await store.get(session_id)
    if not session or session.is_expired():
        if session_id:
            await store.delete(session_id)
        raise HTTPException(status_code=401, detail="unauthenticated")

    # Touch first (update last_active), then attempt silent token refresh
    await store.touch(session_id)
    await _try_refresh(request, session_id)

    # Re-fetch session in case tokens were updated
    session = await store.get(session_id)

    return CurrentUser(
        email=session.email,
        name=session.name,
        role=session.role,
        access_token=session.access_token,
    )


def require_min_role(min_role: str):
    async def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if ROLE_ORDER[user.role] > ROLE_ORDER[min_role]:
            raise HTTPException(status_code=403, detail="forbidden")
        return user

    return dependency


async def require_super_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "super_admin":
        raise HTTPException(status_code=403, detail="forbidden")
    return user
