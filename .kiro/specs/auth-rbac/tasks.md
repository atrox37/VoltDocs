# Implementation Plan: Auth RBAC

## Overview

Bottom-up implementation: DB schema → backend session/Cognito layer → auth middleware → protect existing routes → frontend context/login → admin UI → wiring.

## Tasks

- [x] 1. Database schema and config
  - [x] 1.1 Add `user_roles` and `role_audit_log` tables to SQLite migration
    - Add both `CREATE TABLE IF NOT EXISTS` blocks to the `migrate()` function in `src/db/mod.rs`
    - `user_roles`: email PK, role TEXT CHECK('admin','user'), created_at, last_login
    - `role_audit_log`: id PK, actor_email, target_email, old_role, new_role, changed_at
    - _Requirements: 3.1, 4.1, 4.4, 5.4_

  - [x] 1.2 Extend `AppConfig` with auth environment variables
    - Add to `src/config.rs`: `cognito_domain`, `cognito_client_id`, `cognito_client_secret`, `cognito_redirect_uri`, `dev_user_email`, `initial_admin_email`
    - All new fields read from env with sensible defaults (empty string or `dev@voltdocs.local`)
    - _Requirements: 2.6, 8.1_

  - [x] 1.3 Add `dashmap` dependency to `Cargo.toml`
    - Add `dashmap = "6"` to `[dependencies]` in `backend-rs/Cargo.toml`
    - _Requirements: (infrastructure)_

- [x] 2. Backend auth module — session and role
  - [x] 2.1 Create `src/auth/mod.rs`, `src/auth/session.rs`
    - `Role` enum: `Admin`, `User`, with `from_str()` / `as_str()` methods
    - `SessionData` struct: session_id, email, name, role, created_at, last_active, refresh_token
    - `SessionStore = Arc<DashMap<String, SessionData>>`
    - `new_store()` constructor
    - `SessionData::is_expired()` checking idle (30 min) and absolute (8 hr) timeouts
    - Constants: `SESSION_COOKIE = "voltdocs_session"`, timeout values
    - _Requirements: 1.3, 6.2, 6.4_

  - [x] 2.2 Create `src/auth/cognito.rs` — Cognito client
    - `CognitoClient` struct with `http: reqwest::Client`, domain, client_id, client_secret, redirect_uri
    - `authorization_url(state: &str) -> String` — builds Cognito Hosted UI URL with `response_type=code`, `client_id`, `redirect_uri`, `scope=openid email profile`
    - `exchange_code(code: &str) -> Result<TokenSet, AuthError>` — POST to `/oauth2/token`
    - `refresh_tokens(refresh_token: &str) -> Result<TokenSet, AuthError>` — POST to `/oauth2/token` with `grant_type=refresh_token`
    - `TokenSet` struct: access_token, id_token, refresh_token (Option), expires_in
    - `extract_claims(id_token: &str) -> Result<Claims, AuthError>` — base64-decode JWT payload (no sig verify needed for id_token from trusted Cognito endpoint), extract email and name
    - `AuthError` enum: `TokenExchange`, `InvalidToken`, `NetworkError`
    - _Requirements: 1.2, 1.4, 2.1, 2.2, 2.3, 7.1_

  - [x] 2.3 Create `src/auth/middleware.rs` — Actix auth middleware
    - `CurrentUser` struct: email, name, role (injected into request extensions)
    - `AuthMiddleware` wrapping service factory
    - Logic: if `REQUIRE_AUTH=false` → inject `CurrentUser { email: dev_user_email, name: "Dev User", role: Role::Admin }`, call next
    - Otherwise: read `SESSION_COOKIE` cookie → look up `SessionStore` → if missing/expired return 401 JSON `{"error":"unauthenticated"}` → update `last_active` → check if refresh needed (access token < 5 min to expiry) → inject `CurrentUser`
    - Helper `require_role(req, Role::Admin) -> Option<HttpResponse>` for use inside route handlers
    - _Requirements: 1.1, 1.5, 2.4, 2.5, 2.6, 8.1, 8.2_

  - [x] 2.4 Create `src/auth/routes.rs` — auth API endpoints
    - `GET /api/auth/login-url` → return `{ "url": "<cognito_auth_url>" }` with random `state` param (store state in session store or short-lived map for CSRF)
    - `GET /api/auth/callback?code=&state=` → call `cognito.exchange_code(code)` → extract claims from id_token → upsert `user_roles` row (insert if not exists, update `last_login`) → create `SessionData` → insert into `SessionStore` → set httpOnly cookie → redirect to `/`; on error redirect to `/login?error=auth_failed`
    - `POST /api/auth/logout` → read cookie → remove from `SessionStore` → clear cookie → return 200
    - `GET /api/auth/me` → read cookie → look up session → return `{ email, name, role }` or 401
    - _Requirements: 1.2, 1.3, 1.4, 3.4, 6.1, 6.2, 6.3_

- [x] 3. Checkpoint — Backend auth core
  - Run `cargo check` in `backend-rs/`. Fix all compile errors. No runtime test needed yet.

- [x] 4. Protect existing routes and add user management
  - [x] 4.1 Wire auth middleware and new routes into `src/main.rs`
    - Create `SessionStore` via `auth::session::new_store()`
    - Create `CognitoClient` from config
    - Add `web::Data::new(session_store)` and `web::Data::new(cognito_client)` to app
    - Register auth routes: `/api/auth/login-url`, `/api/auth/callback`, `/api/auth/logout`, `/api/auth/me`
    - Wrap all existing `/api/*` routes (except `/api/health` and auth routes) with `AuthMiddleware`
    - Add background task using `actix_rt::spawn` to sweep expired sessions every 5 minutes
    - Seed `INITIAL_ADMIN_EMAIL` into `user_roles` on startup (INSERT OR IGNORE)
    - _Requirements: 1.1, 1.5, 4.4_

  - [x] 4.2 Add role enforcement to `src/routes/glossary.rs`
    - In `create_term`, `update_term`, `delete_term`: extract `CurrentUser` from `req.extensions()`, call `require_role(user, Role::Admin)` and return 403 if fails
    - Replace all `"dev-user"` hardcoded strings with `user.email`
    - `list_terms` and `audit_logs`: no role restriction (all authenticated users)
    - _Requirements: 3.5, 3.7, 3.8, 5.1_

  - [x] 4.3 Add role enforcement to `src/routes/templates.rs`
    - In `upload_template`, `update_template`, `delete_template`: extract `CurrentUser`, return 403 if not admin
    - Replace `"dev-user"` / `"system"` with `user.email`
    - `list_templates`: no role restriction
    - _Requirements: 3.6, 3.7, 3.8, 5.2_

  - [x] 4.4 Add actor email to audit logs in `src/routes/convert.rs` and `translation.rs`
    - In `create_job` handlers: extract `CurrentUser` email and store in job `user_id` field
    - Add audit log entry for job creation: actor email, job type, source/target lang, input file name
    - _Requirements: 5.3_

  - [x] 4.5 Create `src/routes/users.rs` — user management endpoints
    - `GET /api/users` (admin only): query `user_roles` table, return `[{ email, role, lastLogin }]`
    - `PUT /api/users/{email}/role` (admin only): validate new role is "admin" or "user", check self-demotion guard (count remaining admins before demotion), update `user_roles`, insert into `role_audit_log`, return 200
    - Self-demotion guard: if actor email == target email and new role == "user" and admin count == 1 → return 403 `{"error":"cannot_demote_last_admin"}`
    - Standard_User on either endpoint: 403
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 5.4_

  - [x] 4.6 Register users routes and add comprehensive audit log endpoint
    - Register `GET /api/users` and `PUT /api/users/{email}/role` in `main.rs`
    - Update existing `GET /api/glossary/audit-logs` to require admin role
    - Add `GET /api/audit-logs` endpoint (admin only): query `glossary_audit_logs` + `role_audit_log` joined/unified, support optional `?action=&from=&to=&page=` query params, return max 100 per page sorted by timestamp desc
    - _Requirements: 4.3, 5.6, 5.7, 5.8_

- [x] 5. Checkpoint — Backend integration
  - Run `cargo check`. Manually test with `REQUIRE_AUTH=false`: all existing API calls should still work. `GET /api/auth/me` should return dev identity.

- [x] 6. Frontend auth infrastructure
  - [x] 6.1 Create `src/contexts/AuthContext.tsx`
    - `AuthUser` interface: `{ email: string; name: string; role: 'admin' | 'user' }`
    - `AuthContext` with `user`, `loading`, `logout()`, `refreshUser()`
    - On mount: `GET /api/auth/me` → set user or null
    - `logout()`: `POST /api/auth/logout` → set user null → `navigate('/login')`
    - Export `useAuth()` hook (throws if used outside provider)
    - _Requirements: 1.5, 6.1, 6.3_

  - [x] 6.2 Create `src/components/ProtectedRoute.tsx`
    - If `loading`: render `<div style={{...centred}}><Spin size="large" /></div>`
    - If `user === null`: `<Navigate to="/login" replace />`
    - Else: render `<Outlet />` (or `children` prop)
    - _Requirements: 1.1_

  - [x] 6.3 Create `src/pages/Login.tsx`
    - If user already authenticated: `<Navigate to="/" replace />`
    - Show VoltDocs branding + "使用 Microsoft 账户登录" button (Ant Design `Button` with Microsoft icon)
    - On click: `GET /api/auth/login-url` → `window.location.href = url`
    - If `?error=auth_failed` in URL: show `Alert` error message
    - If `?error=session_expired`: show session expired message
    - _Requirements: 1.1, 1.7_

  - [x] 6.4 Create `src/api/auth.ts` and `src/api/users.ts`
    - `auth.ts`: `getLoginUrl()`, `getMe()`, `logout()`
    - `users.ts`: `listUsers()`, `updateUserRole(email, role)`
    - _Requirements: (frontend infrastructure)_

  - [x] 6.5 Update `src/api/client.ts` to handle 401
    - In the `request()` function: if `res.status === 401` and current path is not `/login`, redirect to `/login?error=session_expired`
    - _Requirements: 1.6_

- [x] 7. Frontend wiring — routing and layout
  - [x] 7.1 Update `src/App.tsx`
    - Wrap entire app with `<AuthProvider>`
    - Add `/login` route (outside `ProtectedRoute`)
    - Wrap the `AppLayout` route group with `<ProtectedRoute>`
    - Add `/admin` route (inside `ProtectedRoute`, rendered only when `user.role === 'admin'`)
    - Import `Login` and `Admin` pages
    - _Requirements: 1.1, 1.7_

  - [x] 7.2 Update `src/layouts/AppLayout.tsx`
    - Import `useAuth()` hook
    - Replace hardcoded `"Yulin Wu"` with `user?.name`
    - Show `user?.email` as subtitle in dropdown
    - Wire logout dropdown item to call `logout()` from AuthContext
    - Add "用户管理" menu item (key `/admin`, icon `TeamOutlined`) in the "系统" group, only rendered when `user?.role === 'admin'`
    - _Requirements: 1.5, 6.1, 6.3_

- [x] 8. Checkpoint — Frontend auth flow (dev mode)
  - Set `REQUIRE_AUTH=false` in backend `.env`
  - Run `npm run dev` in frontend. App should load without login, user avatar should show "Dev User", logout should work (clears state and shows login page).

- [x] 9. Admin UI
  - [x] 9.1 Create `src/pages/Admin.tsx` — user list and role management
    - Ant Design `Table` with columns: email, role (Tag colored by role), last login, actions
    - Role selector (`Select`) per row; on change call `updateUserRole()`, show success/error notification
    - Self-demotion warning: if editing own row to 'user', show `Modal.confirm` warning first
    - Refresh button to reload user list
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 9.2 Add audit log tab to Admin page
    - Ant Design `Tabs` with two tabs: "用户列表" and "操作日志"
    - Audit log tab: `GET /api/audit-logs` → table with columns: time, actor, action, target/resource, details
    - Support filtering by action type (Select), date range (DatePicker.RangePicker)
    - _Requirements: 5.6, 5.7_

- [x] 10. Checkpoint — Full integration test
  - With `REQUIRE_AUTH=false`: verify admin UI loads, role changes work, audit log shows entries
  - Update `.env.example` in `backend-rs/` with all new variables and documentation comments

## New Environment Variables (add to `.env` and `.env.example`)

```
# Auth (set REQUIRE_AUTH=true in production)
REQUIRE_AUTH=false
DEV_USER_EMAIL=dev@voltdocs.local
INITIAL_ADMIN_EMAIL=your-email@company.com

# Cognito (only needed when REQUIRE_AUTH=true)
COGNITO_DOMAIN=https://voltdocs.auth.us-east-1.amazoncognito.com
COGNITO_CLIENT_ID=2fnmsk89dt0066l25kmi68m7qp
COGNITO_CLIENT_SECRET=
COGNITO_REDIRECT_URI=http://localhost:8080/api/auth/callback
```

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["2.3", "2.4"] },
    { "id": 3, "tasks": ["3. Checkpoint"] },
    { "id": 4, "tasks": ["4.1", "4.2", "4.3", "4.4", "4.5"] },
    { "id": 5, "tasks": ["4.6"] },
    { "id": 6, "tasks": ["5. Checkpoint"] },
    { "id": 7, "tasks": ["6.1", "6.2", "6.3", "6.4", "6.5"] },
    { "id": 8, "tasks": ["7.1", "7.2"] },
    { "id": 9, "tasks": ["8. Checkpoint"] },
    { "id": 10, "tasks": ["9.1", "9.2"] },
    { "id": 11, "tasks": ["10. Checkpoint"] }
  ]
}
```
