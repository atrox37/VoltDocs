import { get, post } from './client';

export type UserRole = 'super_admin' | 'manager' | 'user';

export interface AuthUser {
  email: string;
  name: string;
  role: UserRole;
}

export const getLoginUrl = () => get<{ url: string }>('/auth/login-url');
export const getMe = () => get<AuthUser>('/auth/me');
export const logout = () => post<void>('/auth/logout', {});
