from __future__ import annotations

from fastapi import HTTPException

from auth.middleware import CurrentUser
from database import Database


def is_admin(user: CurrentUser) -> bool:
    return user.role in {"super_admin", "manager"}


def job_scope_clause(user: CurrentUser, alias: str = "") -> tuple[str, tuple[str, ...]]:
    if is_admin(user):
        return "", ()
    prefix = f"{alias}." if alias else ""
    return f" AND {prefix}user_id = ?", (user.email,)


def file_scope_clause(user: CurrentUser, alias: str = "") -> tuple[str, tuple[str, ...]]:
    if is_admin(user):
        return "", ()
    prefix = f"{alias}." if alias else ""
    return f" AND {prefix}owner_id = ?", (user.email,)


def require_job_access(db: Database, job_id: str, user: CurrentUser):
    scope_sql, scope_params = job_scope_clause(user)
    row = db.query_one(
        f"""
        SELECT id, user_id, type, status, progress, input_file_id, output_file_id,
               payload_json, result_json, error_message, created_at, started_at, finished_at
        FROM jobs
        WHERE id = ?{scope_sql}
        """,
        (job_id, *scope_params),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    return row


def require_file_access(db: Database, file_id: str, user: CurrentUser):
    scope_sql, scope_params = file_scope_clause(user)
    row = db.query_one(
        f"""
        SELECT id, owner_id, kind, original_name, storage_path, mime_type, size, sha256, created_at
        FROM files
        WHERE id = ?{scope_sql}
        """,
        (file_id, *scope_params),
    )
    if not row:
        raise HTTPException(status_code=404, detail="File not found")
    return row
