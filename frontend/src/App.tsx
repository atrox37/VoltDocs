import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ConfigProvider, App as AntApp } from "antd";
import zhCN from "antd/locale/zh_CN";
import { AuthProvider } from "./contexts/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import RoleRoute from "./components/RoleRoute";
import AppLayout from "./layouts/AppLayout";
import Convert from "./pages/Convert";
import Translate from "./pages/Translate";
import Templates from "./pages/Templates";
import Memory from "./pages/Memory";
import Settings from "./pages/Settings";
import Login from "./pages/Login";
import Admin from "./pages/Admin";
import AuditLogs from "./pages/AuditLogs";

const App = () => (
  <ConfigProvider
    locale={zhCN}
    theme={{
      token: {
        colorPrimary: "#1b3a6b",
        borderRadius: 8,
        fontFamily: "'DM Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      },
    }}
  >
    <AntApp>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route element={<ProtectedRoute />}>
              <Route element={<AppLayout />}>
                {/* Default: redirect root to translate */}
                <Route path="/" element={<Navigate to="/translate" replace />} />
                <Route path="/convert" element={<Convert />} />
                <Route path="/translate" element={<Translate />} />
                <Route path="/templates" element={<Templates />} />
                <Route path="/memory" element={<Memory />} />
                <Route path="/settings" element={<Settings />} />
                <Route element={<RoleRoute minRole="super_admin" />}>
                  <Route path="/admin" element={<Admin />} />
                </Route>
                <Route element={<RoleRoute minRole="manager" />}>
                  <Route path="/audit-logs" element={<AuditLogs />} />
                </Route>
              </Route>
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </AntApp>
  </ConfigProvider>
);

export default App;
