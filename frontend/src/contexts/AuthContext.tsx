import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getMe, logout as apiLogout, AuthUser, UserRole } from '../api/auth';
import { hasMinRole as checkMinRole, isSuperAdmin as checkSuperAdmin } from '../auth/permissions';

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  hasMinRole: (minRole: UserRole) => boolean;
  isSuperAdmin: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const refreshUser = async () => {
    try {
      const data = await getMe();
      setUser(data);
    } catch {
      setUser(null);
    }
  };

  useEffect(() => {
    refreshUser().finally(() => setLoading(false));
  }, []);

  const logout = async () => {
    try {
      await apiLogout();
    } finally {
      setUser(null);
      navigate('/login');
    }
  };

  const hasMinRole = useCallback(
    (minRole: UserRole) => checkMinRole(user?.role, minRole),
    [user?.role],
  );

  const isSuperAdmin = checkSuperAdmin(user?.role);

  const value = useMemo(
    () => ({ user, loading, logout, refreshUser, hasMinRole, isSuperAdmin }),
    [user, loading, hasMinRole, isSuperAdmin],
  );

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
}
