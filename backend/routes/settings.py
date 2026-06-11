from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from auth.middleware import CurrentUser, get_current_user


router = APIRouter()


class UpdateSettingsInput(BaseModel):
    settings: dict[str, str]


@router.get("/api/settings")
async def get_settings(request: Request, user: CurrentUser = Depends(get_current_user)) -> dict:
    rows = request.app.state.db.query_all("SELECT key, value FROM user_settings WHERE user_id = ?", (user.email,))
    return {"settings": {row["key"]: row["value"] or "" for row in rows}}


@router.put("/api/settings")
async def update_settings(body: UpdateSettingsInput, request: Request, user: CurrentUser = Depends(get_current_user)) -> dict:
    now = request.app.state.now()
    for key, value in body.settings.items():
        request.app.state.db.execute(
            """
            INSERT INTO user_settings (user_id, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (user.email, key, value, now),
        )
    return {"ok": True}
