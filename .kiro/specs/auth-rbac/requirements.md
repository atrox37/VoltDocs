# Requirements Document

## Introduction

This feature adds user authentication, role-based access control (RBAC), and comprehensive audit logging to VoltDocs. Authentication leverages the existing AWS Cognito User Pool (`us-east-1_flUobqcda`) with Microsoft Teams OIDC federation, adapted from a Tauri desktop PKCE flow to a browser-based Authorization Code flow. Authorization (role assignment) is managed **locally in SQLite** using the user's email from the JWT — independent of Cognito groups. This keeps role management self-contained within the VoltDocs admin UI.

## Glossary

- **Auth_Service**: The backend Actix-Web middleware responsible for validating JWT tokens, extracting user identity, and enforcing role-based access
- **Cognito**: AWS Cognito User Pool (ID: `us-east-1_flUobqcda`) configured with MicrosoftTeamsOIDC identity provider; used solely for authentication (login), not authorization
- **App_Client**: The Cognito App Client (ID: `2fnmsk89dt0066l25kmi68m7qp`) used for OAuth2 Authorization Code flow
- **Frontend**: The React + Ant Design single-page application served on port 5173 (dev) or via Nginx in Docker
- **Backend**: The Rust Actix-Web API server on port 8080
- **Authorization_Code_Flow**: OAuth2 flow where the browser redirects to Cognito hosted UI, receives an authorization code, and the backend exchanges it for tokens
- **Access_Token**: A JWT issued by Cognito after successful authentication, containing user claims (email, name, sub)
- **Role**: A label assigned to a user in the local `user_roles` SQLite table; one of `admin` or `user`
- **Admin**: A user with the `admin` role who can modify glossary terms, manage templates, manage user roles, and view audit logs
- **Standard_User**: A user with the `user` role who can use translation/conversion features and view glossary terms/templates but cannot modify them
- **Audit_Log**: A timestamped, immutable record of a state-changing action performed by an authenticated user
- **Session**: A server-side representation (httpOnly cookie or token) of an authenticated user's login state
- **Protected_Route**: A Frontend route or Backend endpoint that requires a valid authenticated session
- **User_Roles_Table**: Local SQLite table mapping user email → role, managed by admins within VoltDocs

## Requirements

### Requirement 1: Browser-Based Authentication via Cognito + Microsoft Teams

**User Story:** As a VoltDocs user, I want to log in using my Microsoft Teams account through the browser, so that I can access the application without managing separate credentials.

#### Acceptance Criteria

1. WHEN an unauthenticated user accesses a Protected_Route, THE Frontend SHALL redirect the user to the Cognito hosted UI login page using the Authorization_Code_Flow within 1 second.
2. WHEN Cognito redirects back with an authorization code, THE Backend SHALL exchange the authorization code for an Access_Token, ID token, and refresh token via the Cognito token endpoint within 5 seconds.
3. WHEN the token exchange succeeds, THE Backend SHALL establish a Session for the user with a 30-minute idle timeout and an 8-hour absolute expiry, and return a session cookie to the Frontend.
4. IF the token exchange fails, THEN THE Backend SHALL return an HTTP 401 response with an error message indicating the reason for failure.
5. WHILE a user has a valid Session, THE Frontend SHALL include session credentials in all API requests to Protected_Routes.
6. WHEN the Frontend receives an HTTP 401 response from any Protected_Route request, THE Frontend SHALL redirect the user to the Cognito hosted UI login page.
7. IF an authenticated user navigates to the login page, THEN THE Frontend SHALL redirect the user to the Dashboard without requiring re-authentication.

### Requirement 2: JWT Validation and User Identity Extraction

**User Story:** As a backend developer, I want the API to validate incoming tokens and extract user identity, so that every request is tied to a known user.

#### Acceptance Criteria

1. WHEN an API request includes a Bearer token, THE Auth_Service SHALL validate the token signature against the Cognito JWKS endpoint (with local caching of public keys).
2. WHEN the token signature is valid, THE Auth_Service SHALL verify the token has not expired and the audience claim matches the App_Client ID.
3. WHEN token validation succeeds, THE Auth_Service SHALL extract the user's email, name, and sub from the token claims.
4. IF a request to a Protected_Route contains an invalid or expired token, THEN THE Auth_Service SHALL return an HTTP 401 response.
5. IF a request to a Protected_Route contains no token and `REQUIRE_AUTH` is `true`, THEN THE Auth_Service SHALL return an HTTP 401 response.
6. WHILE `REQUIRE_AUTH` is `false`, THE Auth_Service SHALL allow unauthenticated requests and assign a default development identity.

### Requirement 3: Local Role-Based Access Control (SQLite)

**User Story:** As an organization administrator, I want to restrict glossary and template modifications to admin users, so that only authorized personnel can change shared resources.

#### Acceptance Criteria

1. THE Auth_Service SHALL determine the user's Role by querying the local `user_roles` SQLite table using the email extracted from the Access_Token.
2. WHEN a user's email exists in `user_roles` with `role = 'admin'`, THE Auth_Service SHALL assign the `admin` Role.
3. WHEN a user's email does not exist in `user_roles` or has `role = 'user'`, THE Auth_Service SHALL assign the `user` Role.
4. WHEN a user logs in for the first time and has no entry in `user_roles`, THE Backend SHALL auto-create an entry with `role = 'user'`.
5. WHEN a Standard_User attempts to create, update, or delete a glossary term, THE Backend SHALL return an HTTP 403 response with an error message indicating insufficient permissions.
6. WHEN a Standard_User attempts to upload, update, or delete a template, THE Backend SHALL return an HTTP 403 response with an error message indicating insufficient permissions.
7. WHEN an Admin performs a glossary or template modification, THE Backend SHALL process the request and return a success response (HTTP 2xx).
8. THE Backend SHALL allow all authenticated users to access translation, conversion, file download, and read-only glossary/template listing endpoints regardless of Role.

### Requirement 4: Admin User Management

**User Story:** As an admin, I want to promote or demote other users' roles within VoltDocs, so that I don't need to access the AWS console.

#### Acceptance Criteria

1. WHEN an Admin requests the user list, THE Backend SHALL return all entries from `user_roles` including email, role, and last login time.
2. WHEN an Admin updates another user's role, THE Backend SHALL update the `user_roles` table and record an Audit_Log entry.
3. WHEN a Standard_User attempts to view or modify user roles, THE Backend SHALL return an HTTP 403 response.
4. THE Backend SHALL prevent an Admin from demoting themselves if they are the last remaining admin.
5. THE Backend SHALL seed the `user_roles` table with at least one admin email on first startup (configured via environment variable `INITIAL_ADMIN_EMAIL`).

### Requirement 5: Audit Logging

**User Story:** As an administrator, I want a record of who performed each action, so that I can track changes and investigate issues.

#### Acceptance Criteria

1. WHEN an authenticated user creates, updates, or deletes a glossary term, THE Backend SHALL record an Audit_Log entry with the actor's email, action type, before-state, and after-state.
2. WHEN an authenticated user uploads, updates, or deletes a template, THE Backend SHALL record an Audit_Log entry with the actor's email, action type, and affected resource identifier.
3. WHEN an authenticated user creates a translation or conversion job, THE Backend SHALL record an Audit_Log entry with the actor's email, job type, source language, target language, and input file name.
4. WHEN an Admin changes another user's role, THE Backend SHALL record an Audit_Log entry with the actor's email, target user email, old role, and new role.
5. THE Audit_Log entry SHALL include a UTC timestamp with millisecond precision, the actor's email address, the action name, and relevant resource identifiers.
6. WHEN an Admin requests audit logs, THE Backend SHALL return entries filtered by optional date range and action type parameters, sorted by timestamp descending, with pagination (max 100 per page).
7. IF a user without the `admin` Role requests audit log entries, THEN THE Backend SHALL return an HTTP 403 response.
8. THE Backend SHALL prevent modification or deletion of existing Audit_Log entries through any user-facing API.

### Requirement 6: Session Management and Logout

**User Story:** As a user, I want to log out and have my session invalidated, so that no one else can use my session on a shared workstation.

#### Acceptance Criteria

1. WHEN a user initiates logout, THE Frontend SHALL call the Backend logout endpoint.
2. WHEN the Backend receives a logout request, THE Backend SHALL invalidate the user's Session and clear the session cookie.
3. WHEN the Backend successfully invalidates the Session, THE Frontend SHALL redirect the user to the login page.
4. IF a request uses an invalidated Session, THEN THE Backend SHALL return an HTTP 401 response.

### Requirement 7: Token Refresh

**User Story:** As a user, I want my session to stay active while I am working, so that I do not get logged out during a long translation job.

#### Acceptance Criteria

1. WHEN an Access_Token is within 5 minutes of expiration and the user has an active Session, THE Backend SHALL use the refresh token to obtain a new Access_Token from Cognito.
2. WHEN the token refresh succeeds, THE Backend SHALL update the Session with the new Access_Token.
3. IF the refresh token is expired or revoked, THEN THE Backend SHALL invalidate the Session and THE Frontend SHALL redirect the user to the login page.

### Requirement 8: Development Mode Bypass

**User Story:** As a developer, I want to run the application locally without Cognito, so that I can develop and test features without network access to AWS.

#### Acceptance Criteria

1. WHILE `REQUIRE_AUTH` is `false`, THE Backend SHALL skip token validation and assign a configurable default user identity (email from `DEV_USER_EMAIL` env var) to all requests.
2. WHILE `REQUIRE_AUTH` is `false`, THE Backend SHALL assign the `admin` Role to the default development identity.
3. WHILE `REQUIRE_AUTH` is `false`, THE Frontend SHALL skip the login redirect and display the application directly.
