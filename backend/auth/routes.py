from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from auth.cognito import CognitoClient, extract_claims, generate_state
from auth.session import SESSION_COOKIE, SessionData


router = APIRouter()


@router.get("/api/auth/login-url")
async def login_url(request: Request) -> dict:
    cfg = request.app.state.config
    cognito: CognitoClient = request.app.state.cognito_client
    if not cfg.require_auth and not cfg.cognito_domain:
        return {"url": f"/?dev_login=true&state={generate_state()}"}
    return {"url": cognito.authorization_url(generate_state())}


@router.get("/api/auth/callback")
async def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    _ = state
    cfg = request.app.state.config
    frontend = cfg.frontend_url  # e.g. http://localhost:5173

    if error or not code:
        return RedirectResponse(f"{frontend}/login?error=auth_failed", status_code=302)

    db = request.app.state.db
    cognito: CognitoClient = request.app.state.cognito_client
    try:
        token_set = await cognito.exchange_code(code)
        claims = extract_claims(token_set.id_token)
    except Exception:
        return RedirectResponse(f"{frontend}/login?error=auth_failed", status_code=302)
    now = request.app.state.now()
    db.execute("INSERT OR IGNORE INTO user_roles (email, role, created_at) VALUES (?, 'user', ?)", (claims.email, now))
    db.execute("UPDATE user_roles SET last_login = ? WHERE email = ?", (now, claims.email))
    role = db.query_value("SELECT role FROM user_roles WHERE email = ?", (claims.email,)) or "user"
    session_id = str(uuid.uuid4())
    session = SessionData(
        session_id=session_id,
        email=claims.email,
        name=claims.name,
        role=role,
        created_at=datetime.now(timezone.utc),
        last_active=datetime.now(timezone.utc),
        access_token=token_set.access_token,
        refresh_token=token_set.refresh_token,
    )
    await request.app.state.session_store.set(session_id, session)
    response = RedirectResponse(f"{frontend}/", status_code=302)
    response.set_cookie(
        SESSION_COOKIE, session_id,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/api/auth/logout")
async def logout(request: Request) -> dict:
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        await request.app.state.session_store.delete(session_id)
    response = Response(content='{"ok": true}', media_type="application/json")
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/api/auth/me")
async def me(request: Request) -> dict:
    cfg = request.app.state.config
    if not cfg.require_auth:
        return {"email": cfg.dev_user_email, "name": "Dev User", "role": "super_admin"}
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        raise HTTPException(status_code=401, detail="unauthenticated")
    session = await request.app.state.session_store.get(session_id)
    if not session or session.is_expired():
        if session_id:
            await request.app.state.session_store.delete(session_id)
        raise HTTPException(status_code=401, detail="unauthenticated")
    await request.app.state.session_store.touch(session_id)

    # 修正历史遗留的 cognito:username 格式的 name
    name = session.name
    if not name or "_" in name or len(name) > 50:
        from auth.cognito import _derive_name_from_email
        name = _derive_name_from_email(session.email) if session.email else session.email

    return {"email": session.email, "name": name, "role": session.role}
