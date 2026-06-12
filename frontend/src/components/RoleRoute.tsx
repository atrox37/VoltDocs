import { Navigate, Outlet } from 'react-router-dom';
import type { UserRole } from '../api/auth';
import { hasMinRole } from '../auth/permissions';
import { useAuth } from '../contexts/AuthContext';

interface RoleRouteProps {
  minRole: UserRole;
}

/** Redirects to the default page when the current user lacks the required role. */
export default function RoleRoute({ minRole }: RoleRouteProps) {
  const { user } = useAuth();

  if (!user || !hasMinRole(user.role, minRole)) {
    return <Navigate to="/translate" replace />;
  }

  return <Outlet />;
}
