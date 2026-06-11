from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


SESSION_COOKIE = "voltdocs_session"
IDLE_TIMEOUT_MINUTES = 240    # 4 hours idle → logout
ABSOLUTE_TIMEOUT_DAYS = 30    # 30 days hard cap

ROLE_ORDER = {"super_admin": 0, "manager": 1, "user": 2}

# Refresh the access token when it has less than this many seconds left
_ACCESS_TOKEN_REFRESH_BUFFER_SECONDS = 300  # 5 minutes


def _decode_jwt_exp(token: str | None) -> datetime | None:
    """Return the expiry datetime from a JWT's exp claim, or None on failure."""
    if not token:
        return None
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        exp = payload.get("exp")
        if exp is None:
            return None
        return datetime.fromtimestamp(int(exp), tz=timezone.utc)
    except Exception:
        return None


@dataclass
class SessionData:
    session_id: str
    email: str
    name: str
    role: str
    created_at: datetime
    last_active: datetime
    access_token: str | None = None
    refresh_token: str | None = None

    def is_expired(self) -> bool:
        now = datetime.now(timezone.utc)
        idle_expired = now - self.last_active > timedelta(minutes=IDLE_TIMEOUT_MINUTES)
        absolute_expired = now - self.created_at > timedelta(days=ABSOLUTE_TIMEOUT_DAYS)
        return idle_expired or absolute_expired

    def access_token_needs_refresh(self) -> bool:
        """True when the access token is missing, expired, or about to expire."""
        if not self.refresh_token:
            return False  # nothing to do without a refresh token
        exp = _decode_jwt_exp(self.access_token)
        if exp is None:
            return True  # can't determine expiry → assume refresh needed
        now = datetime.now(timezone.utc)
        return (exp - now).total_seconds() < _ACCESS_TOKEN_REFRESH_BUFFER_SECONDS


class SessionStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[str, SessionData] = {}

    async def get(self, session_id: str) -> SessionData | None:
        async with self._lock:
            return self._sessions.get(session_id)

    async def set(self, session_id: str, session: SessionData) -> None:
        async with self._lock:
            self._sessions[session_id] = session

    async def delete(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def touch(self, session_id: str) -> SessionData | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.last_active = datetime.now(timezone.utc)
            return session

    async def update_tokens(
        self,
        session_id: str,
        access_token: str,
        refresh_token: str | None,
    ) -> None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.access_token = access_token
                if refresh_token:
                    session.refresh_token = refresh_token
                session.last_active = datetime.now(timezone.utc)

    async def sweep_expired(self) -> int:
        async with self._lock:
            expired = [key for key, value in self._sessions.items() if value.is_expired()]
            for key in expired:
                self._sessions.pop(key, None)
            return len(expired)
