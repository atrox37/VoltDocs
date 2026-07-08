import type { UserRole } from "../api/auth";

/** Mirrors backend auth/session.py ROLE_ORDER */
export const ROLE_ORDER: Record<UserRole, number> = {
  super_admin: 0,
  manager: 1,
  user: 2,
};

export const ROLE_LABEL: Record<UserRole, string> = {
  super_admin: "Super Admin",
  manager: "Manager",
  user: "User",
};

export const ROLE_COLOR: Record<UserRole, string> = {
  super_admin: "red",
  manager: "orange",
  user: "blue",
};

export const ROLE_OPTIONS: { value: UserRole; label: string }[] = [
  { value: "super_admin", label: ROLE_LABEL.super_admin },
  { value: "manager", label: ROLE_LABEL.manager },
  { value: "user", label: ROLE_LABEL.user },
];

export function hasMinRole(
  userRole: UserRole | undefined | null,
  minRole: UserRole,
): boolean {
  if (!userRole) {
    return false;
  }
  return ROLE_ORDER[userRole] <= ROLE_ORDER[minRole];
}

export function isSuperAdmin(userRole: UserRole | undefined | null): boolean {
  return userRole === "super_admin";
}
