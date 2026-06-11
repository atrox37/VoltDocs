from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from auth.middleware import CurrentUser, require_min_role, require_super_admin


router = APIRouter()


class UpdateRoleBody(BaseModel):
    role: str


@router.get("/api/users")
async def list_users(request: Request, _: CurrentUser = Depends(require_super_admin)):
    rows = request.app.state.db.query_all("SELECT email, role, last_login FROM user_roles ORDER BY email")
    return [{"email": row["email"], "role": row["role"], "lastLogin": row["last_login"]} for row in rows]


@router.put("/api/users/{email}/role")
async def update_role(email: str, body: UpdateRoleBody, request: Request, actor: CurrentUser = Depends(require_super_admin)) -> dict:
    if body.role not in {"super_admin", "manager", "user"}:
        raise HTTPException(status_code=400, detail="invalid_role")
    db = request.app.state.db
    existing = db.query_one("SELECT role FROM user_roles WHERE email = ?", (email,))
    if not existing:
        raise HTTPException(status_code=404, detail="user_not_found")
    if actor.email == email and body.role != "super_admin":
        count = db.query_value("SELECT COUNT(*) FROM user_roles WHERE role = 'super_admin'") or 0
        if int(count) == 1:
            raise HTTPException(status_code=403, detail="cannot_demote_last_super_admin")
    db.execute("UPDATE user_roles SET role = ? WHERE email = ?", (body.role, email))
    db.execute(
        "INSERT INTO role_audit_log (id, actor_email, target_email, old_role, new_role, changed_at) VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), actor.email, email, existing["role"], body.role, request.app.state.now()),
    )
    return {"ok": True}


@router.get("/api/audit-logs")
async def audit_logs(
    request: Request,
    action: str | None = None,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    page: int = 1,
    page_size: int = Query(default=20, alias="pageSize", ge=10, le=100),
    _: CurrentUser = Depends(require_min_role("manager")),
) -> dict:
    page = max(1, page)
    offset = (page - 1) * page_size

    # Count total for pagination
    total_row = request.app.state.db.query_one(
        """
        SELECT (
            SELECT COUNT(*) FROM glossary_audit_logs
            WHERE (? = '' OR action = ?)
              AND (? = '' OR created_at >= ?)
              AND (? = '' OR created_at <= ?)
        ) + (
            SELECT COUNT(*) FROM role_audit_log
            WHERE (? = '' OR 'role_change' = ?)
              AND (? = '' OR changed_at >= ?)
              AND (? = '' OR changed_at <= ?)
        ) AS total
        """,
        (action or "", action or "", from_ or "", from_ or "", to or "", to or "",
         action or "", action or "", from_ or "", from_ or "", to or "", to or ""),
    )
    total = int(total_row["total"]) if total_row else 0

    rows = request.app.state.db.query_all(
        """
        SELECT id, created_at AS time, actor, action,
               json_object('termId', term_id, 'before', before_json, 'after', after_json) AS details
        FROM glossary_audit_logs
        WHERE (? = '' OR action = ?)
          AND (? = '' OR created_at >= ?)
          AND (? = '' OR created_at <= ?)
        UNION ALL
        SELECT id, changed_at AS time, actor_email AS actor, 'role_change' AS action,
               json_object('targetEmail', target_email, 'oldRole', old_role, 'newRole', new_role) AS details
        FROM role_audit_log
        WHERE (? = '' OR 'role_change' = ?)
          AND (? = '' OR changed_at >= ?)
          AND (? = '' OR changed_at <= ?)
        ORDER BY time DESC
        LIMIT ? OFFSET ?
        """,
        (action or "", action or "", from_ or "", from_ or "", to or "", to or "",
         action or "", action or "", from_ or "", from_ or "", to or "", to or "",
         page_size, offset),
    )
    return {
        "logs": [
            {
                "id": row["id"],
                "time": row["time"],
                "actor": row["actor"],
                "action": row["action"],
                "details": json.loads(row["details"]) if row["details"] else None,
            }
            for row in rows
        ],
        "page": page,
        "pageSize": page_size,
        "total": total,
    }


@router.get("/api/audit-logs/export-csv")
async def export_audit_logs_csv(
    request: Request,
    _: CurrentUser = Depends(require_min_role("manager")),
):
    """导出操作日志为 CSV"""
    import csv
    import io
    from fastapi.responses import StreamingResponse

    rows = request.app.state.db.query_all(
        """
        SELECT id, created_at AS time, actor, action,
               json_object('termId', term_id, 'before', before_json, 'after', after_json) AS details
        FROM glossary_audit_logs
        UNION ALL
        SELECT id, changed_at AS time, actor_email AS actor, 'role_change' AS action,
               json_object('targetEmail', target_email, 'oldRole', old_role, 'newRole', new_role) AS details
        FROM role_audit_log
        ORDER BY time DESC
        """
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["时间", "操作人", "操作类型", "详情"])
    for row in rows:
        writer.writerow([row["time"], row["actor"], row["action"], row["details"] or ""])
    csv_bytes = buffer.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename*=UTF-8\'\'audit_logs.csv'},
    )
