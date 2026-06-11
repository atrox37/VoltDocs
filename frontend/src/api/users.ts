import { get, put } from './client';
import type { UserRole } from './auth';

export interface UserEntry {
  email: string;
  role: UserRole;
  lastLogin: string | null;
}

export const listUsers = () => get<UserEntry[]>('/users');
export const updateUserRole = (email: string, role: UserRole) =>
  put<{ ok: boolean }>(`/users/${encodeURIComponent(email)}/role`, { role });
