# Design Document: Auth RBAC

## Overview

This design adds browser-based authentication (Cognito Authorization Code Flow), role-based access control, and audit logging to VoltDocs. The existing architecture is Actix-Web (Rust) backend + React/Ant Design frontend communicating via REST API — no Tauri, no desktop.

### Key Design Decisions

1. **Session cookie, not Bearer token in JS** — The backend exchanges the Cognito auth code and issues an httpOnly session cookie. The frontend never touches the JWT directly. This avoids XSS token theft.
2. **In-memory session store** — Sessions are kept in a `DashMap<SessionId, SessionData>` in the Actix app state. Simple, fast, no extra Redis dependency. Sessions expire after 30 min idle / 8 hr absolute.
3. **Role from local SQLite** — Cognito only handles authn. Authz (admin vs user) is a local `user_roles` table in the existing SQLite DB. Role is resolved on every request from the extracted email.
4. **`REQUIRE_AUTH=false` dev bypass** — When false, a fake `DEV_USER_EMAIL` identity (defaulting to admin) is injected, so frontend development works without Cognito.
5. **Actix middleware for auth** — A single `AuthMiddleware` wraps all protected routes. It reads the session cookie, validates it, resolves the role, and injects a `CurrentUser` extension into the request.
6. **Frontend AuthContext + ProtectedRoute** — React context holds the current user state. A `ProtectedRoute` component redirects to `/login` if unauthenticated. The existing `AppLayout` is updated to show the real user name and a working logout button.

## Architecture

```
Browser
  │  cookie: voltdocs_session=<id>
  │
  ├── GET /api/auth/me          ← check session on app load
  ├── GET /api/auth/login-url   ← get Cognito redirect URL
  ├── GET /api/auth/callback?code=... ← exchange code, set cookie
  ├── POST /api/auth/logout     ← clear session
  │
  └── GET/POST /api/*           ← all other routes go through AuthMiddleware

Backend
  AuthMiddleware
    ├── REQUIRE_AUTH=false → inject DEV identity, skip everything
    ├── read voltdocs_session cookie
    ├── look up SessionStore → SessionData { email, name, role, ... }
    ├── if missing/expired → 401
    └── inject CurrentUser into request extensions

  SessionStore: DashMap<String, SessionData>
    └── Background task sweeps expired sessions every 5 min

  CognitoClient
    ├── exchange_code(code) → TokenSet
    ├── refresh_token(refresh_token) → new access_token
    └── JWKS cache (reqwest, refreshed every hour)

  Role resolution: email → user_roles table → Role::Admin | Role::User
```

## Components and Interfaces

### Backend: New Files

#### `src/auth/mod.rs`
```rust
pub mod cognito;
pub mod middleware;
pub mod session;
pub mod routes;
```

#### `src/auth/session.rs`
```rust
use std::sync::Arc;
use dashmap::DashMap;
use chrono::{DateTime, Utc, Duration};

pub const SESSION_COOKIE: &str = "voltdocs_session";
pub const IDLE_TIMEOUT_MINS: i64 = 30;
pub const ABSOLUTE_TIMEOUT_HOURS: i64 = 8;

#[derive(Clone, Debug)]
pub struct SessionData {
    pub session_id: String,
    pub email: String,
    pub name: String,
    pub role: Role,
    pub created_at: DateTime<Utc>,
    pub last_active: DateTime<Utc>,
    /// Cognito refresh token for silent renewal
    pub refresh_token: Option<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Role { Admin, User }

pub type SessionStore = Arc<DashMap<String, SessionData>>;

pub fn new_store() -> SessionStore {
    Arc::new(DashMap::new())
}

impl SessionData {
    pub fn is_expired(&self) -> bool {
        let now = Utc::now();
        now - self.last_active > Duration::minutes(IDLE_TIMEOUT_MINS)
            || now - self.created_at > Duration::hours(ABSOLUTE_TIMEOUT_HOURS)
    }
}
```

#### `src/auth/cognito.rs`
```rust
// Cognito constants (from requirements glossary)
pub const USER_POOL_ID: &str = "us-east-1_flUobqcda";
pub const APP_CLIENT_ID: &str = "2fnmsk89dt0066l25kmi68m7qp";
pub const COGNITO_DOMAIN: &str = "https://auth.voltdocs.com"; // from env COGNITO_DOMAIN

pub struct CognitoClient {
    http: reqwest::Client,
    domain: String,
    client_id: String,
    client_secret: Option<String>,
    redirect_uri: String,
}

impl CognitoClient {
    /// Build the Cognito Hosted UI URL for Authorization Code flow
    pub fn authorization_url(&self, state: &str) -> String;

    /// Exchange authorization code for TokenSet
    pub async fn exchange_code(&self, code: &str) -> Result<TokenSet, AuthError>;

    /// Use refresh token to get new access token
    pub async fn refresh_token(&self, refresh_token: &str) -> Result<TokenSet, AuthError>;
}

pub struct TokenSet {
    pub access_token: String,
    pub id_token: String,
    pub refresh_token: Option<String>,
    pub expires_in: u64,
}
```

#### `src/auth/middleware.rs`
```rust
// Actix middleware that runs on every request to a protected route.
// Injects CurrentUser into request extensions.

#[derive(Clone, Debug)]
pub struct CurrentUser {
    pub email: String,
    pub name: String,
    pub role: Role,
}

// The middleware:
// 1. If REQUIRE_AUTH=false → inject dev user (admin), pass through
// 2. Read SESSION_COOKIE from request
// 3. Look up in SessionStore → SessionData
// 4. If missing or expired → return 401 JSON
// 5. Update last_active timestamp
// 6. Inject CurrentUser into request.extensions()
```

#### `src/auth/routes.rs`
```rust
// GET  /api/auth/login-url   → { url: String }
// GET  /api/auth/callback    → sets cookie, redirects to /
// POST /api/auth/logout      → clears cookie, invalidates session
// GET  /api/auth/me          → { email, name, role } or 401
```

#### `src/routes/users.rs` (new)
```rust
// GET  /api/users            → list all (admin only)
// PUT  /api/users/{email}/role → { role: "admin"|"user" } (admin only)
```

### Backend: Modified Files

#### `src/db/mod.rs`
Add to `migrate()`:
```sql
CREATE TABLE IF NOT EXISTS user_roles (
    email       TEXT PRIMARY KEY NOT NULL,
    role        TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('admin','user')),
    created_at  TEXT NOT NULL,
    last_login  TEXT
);

CREATE TABLE IF NOT EXISTS role_audit_log (
    id          TEXT PRIMARY KEY,
    actor_email TEXT NOT NULL,
    target_email TEXT NOT NULL,
    old_role    TEXT NOT NULL,
    new_role    TEXT NOT NULL,
    changed_at  TEXT NOT NULL
);
```

#### `src/config.rs`
Add new fields:
```rust
pub cognito_domain: String,      // COGNITO_DOMAIN env
pub cognito_client_id: String,   // COGNITO_CLIENT_ID env  
pub cognito_client_secret: String, // COGNITO_CLIENT_SECRET env
pub cognito_redirect_uri: String,  // COGNITO_REDIRECT_URI env
pub dev_user_email: String,      // DEV_USER_EMAIL env (default: dev@voltdocs.local)
pub initial_admin_email: String, // INITIAL_ADMIN_EMAIL env
```

#### `src/routes/glossary.rs`, `templates.rs`
Replace hardcoded `"dev-user"` with `req.extensions().get::<CurrentUser>().email`.
Add admin role check to mutating endpoints (create/update/delete).

#### `src/main.rs`
- Add `SessionStore` and `CognitoClient` to app data
- Register auth routes
- Register users routes
- Start background sweep task for expired sessions
- Seed `INITIAL_ADMIN_EMAIL` into `user_roles` on startup

### Frontend: New Files

#### `src/contexts/AuthContext.tsx`
```typescript
interface AuthUser { email: string; name: string; role: 'admin' | 'user' }

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

// On mount: GET /api/auth/me → set user or null
// logout(): POST /api/auth/logout → clear user → navigate('/login')
```

#### `src/components/ProtectedRoute.tsx`
```typescript
// If loading: show Ant Design Spin
// If user === null: <Navigate to="/login" replace />
// Else: <Outlet /> (or children)
```

#### `src/pages/Login.tsx`
```typescript
// If user already logged in: redirect to /
// Show "Sign in with Microsoft" button → GET /api/auth/login-url → window.location.href = url
// Shows error message if ?error= param present in URL
```

#### `src/pages/Admin.tsx`
```typescript
// List users table: email, role, last login
// Role selector (admin/user) per row
// Self-demotion guard: warn if last admin
// Role Change History tab (GET /api/audit-logs?action=role_change)
```

#### `src/api/auth.ts`
```typescript
export const getLoginUrl = () => get<{ url: string }>('/auth/login-url');
export const getMe = () => get<AuthUser>('/auth/me');
export const logout = () => post<void>('/auth/logout');
```

#### `src/api/users.ts`
```typescript
export const listUsers = () => get<UserEntry[]>('/users');
export const updateUserRole = (email: string, role: string) =>
  put<void>(`/users/${encodeURIComponent(email)}/role`, { role });
```

### Frontend: Modified Files

#### `src/App.tsx`
- Wrap with `<AuthProvider>`
- Wrap all routes inside `<ProtectedRoute>`
- Add `/login` route (no auth required)
- Add `/admin` route (admin only, via `<AdminRoute>`)

#### `src/layouts/AppLayout.tsx`
- Replace hardcoded `"Yulin Wu"` with `user.name` and `user.email` from `useAuth()`
- Wire logout dropdown item to `logout()` from AuthContext
- Add Admin nav item (only shown when `user.role === 'admin'`)

#### `src/api/client.ts`
- On 401 response: call `window.location.href = '/login'` (redirect to login)

## Data Models

### SQLite: New Tables
```sql
-- Role assignments
CREATE TABLE IF NOT EXISTS user_roles (
    email       TEXT PRIMARY KEY NOT NULL,
    role        TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('admin','user')),
    created_at  TEXT NOT NULL,
    last_login  TEXT
);

-- Role change audit trail
CREATE TABLE IF NOT EXISTS role_audit_log (
    id           TEXT PRIMARY KEY,
    actor_email  TEXT NOT NULL,
    target_email TEXT NOT NULL,
    old_role     TEXT NOT NULL,
    new_role     TEXT NOT NULL,
    changed_at   TEXT NOT NULL
);
```

### In-Memory Session
```rust
struct SessionData {
    session_id: String,
    email: String,
    name: String,
    role: Role,
    created_at: DateTime<Utc>,
    last_active: DateTime<Utc>,
    refresh_token: Option<String>,
}
```

### API Shapes

#### `GET /api/auth/me` → 200
```json
{ "email": "user@company.com", "name": "Yulin Wu", "role": "admin" }
```

#### `GET /api/auth/login-url` → 200
```json
{ "url": "https://auth.voltdocs.com/oauth2/authorize?..." }
```

#### `GET /api/auth/callback?code=...&state=...` → 302 to `/`

#### `POST /api/auth/logout` → 200, clears cookie

#### `GET /api/users` (admin only) → 200
```json
[{ "email": "...", "role": "admin", "lastLogin": "2024-..." }]
```

#### `PUT /api/users/{email}/role` (admin only)
```json
{ "role": "user" }
```

## New Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `COGNITO_DOMAIN` | prod | — | e.g. `https://voltdocs.auth.us-east-1.amazoncognito.com` |
| `COGNITO_CLIENT_ID` | prod | — | App client ID |
| `COGNITO_CLIENT_SECRET` | prod | — | App client secret |
| `COGNITO_REDIRECT_URI` | prod | — | e.g. `http://localhost:8080/api/auth/callback` |
| `INITIAL_ADMIN_EMAIL` | yes | — | Seeded as admin on first startup |
| `DEV_USER_EMAIL` | dev | `dev@voltdocs.local` | Identity used when `REQUIRE_AUTH=false` |
| `REQUIRE_AUTH` | — | `false` | Set to `true` in production |

## Error Handling

| Scenario | Backend | Frontend |
|---|---|---|
| No session cookie | 401 JSON | Redirect to `/login` |
| Expired session | 401 JSON | Redirect to `/login` |
| Standard_User on admin endpoint | 403 JSON | Show Ant Design error message |
| Cognito code exchange fails | 401, redirect to `/login?error=auth_failed` | Show error on login page |
| Refresh token expired | Invalidate session, 401 | Redirect to `/login` |
| Last admin self-demotion | 403 JSON | Frontend warning before submit |
| `REQUIRE_AUTH=false` | Inject dev identity | Skip login page entirely |

## New Cargo Dependencies

```toml
dashmap = "6"           # concurrent session store
actix-service = "2"     # middleware trait
cookie = "0.18"         # httpOnly cookie building (actix-web re-exports this)
rand = "0.8"            # already present — session ID generation
```
