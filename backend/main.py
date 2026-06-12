from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from auth.cognito import CognitoClient
from auth.routes import router as auth_router
from auth.session import SessionStore
from config import load_config
from database import Database
from routes import convert, dashboard, files, glossary, health, settings, templates, translation, users
from services.storage import ensure_dirs


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def create_app() -> FastAPI:
    cfg = load_config()
    ensure_dirs(cfg.data_dir)
    db = Database(cfg.db_path)
    if cfg.initial_admin_email:
        db.execute(
            "INSERT OR IGNORE INTO user_roles (email, role, created_at) VALUES (?, 'super_admin', ?)",
            (cfg.initial_admin_email, utc_now()),
        )

    app = FastAPI(title="VoltDocs Python Backend")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.config = cfg
    app.state.db = db
    app.state.now = utc_now
    app.state.session_store = SessionStore()
    app.state.cognito_client = CognitoClient(
        cfg.cognito_domain,
        cfg.cognito_client_id,
        cfg.cognito_client_secret,
        cfg.cognito_redirect_uri,
    )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException):
        if isinstance(exc.detail, dict):
            if "error" in exc.detail:
                return JSONResponse(status_code=exc.status_code, content=exc.detail)
            return JSONResponse(status_code=exc.status_code, content={"error": json.dumps(exc.detail, ensure_ascii=False)})
        if isinstance(exc.detail, list):
            return JSONResponse(status_code=exc.status_code, content={"error": json.dumps(exc.detail, ensure_ascii=False)})
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    @app.exception_handler(Exception)
    async def generic_exception_handler(_: Request, exc: Exception):
        return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.on_event("startup")
    async def startup() -> None:
        async def sweep_sessions() -> None:
            while True:
                await asyncio.sleep(300)
                await app.state.session_store.sweep_expired()

        app.state.session_sweeper = asyncio.create_task(sweep_sessions())

    @app.on_event("shutdown")
    async def shutdown() -> None:
        task = getattr(app.state, "session_sweeper", None)
        if task:
            task.cancel()

    app.include_router(health.router)
    app.include_router(auth_router)
    app.include_router(dashboard.router)
    app.include_router(convert.router)
    app.include_router(translation.router)
    app.include_router(glossary.router)
    app.include_router(templates.router)
    app.include_router(files.router)
    app.include_router(settings.router)
    app.include_router(users.router)
    return app


app = create_app()
