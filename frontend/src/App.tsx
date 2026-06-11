import { BrowserRouter, Route, Routes } from "react-router-dom";
import { ConfigProvider, App as AntApp } from "antd";
import zhCN from "antd/locale/zh_CN";
import { AuthProvider } from "./contexts/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import AppLayout from "./layouts/AppLayout";
import Dashboard from "./pages/Dashboard";
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
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            {/* Public route — no auth required */}
            <Route path="/login" element={<Login />} />

            {/* Protected routes — require authentication */}
            <Route element={<ProtectedRoute />}>
              <Route element={<AppLayout />}>
                <Route path="/" element={<Dashboard />} />
                <Route path="/convert" element={<Convert />} />
                <Route path="/translate" element={<Translate />} />
                <Route path="/templates" element={<Templates />} />
                <Route path="/memory" element={<Memory />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="/admin" element={<Admin />} />
                <Route path="/audit-logs" element={<AuditLogs />} />
              </Route>
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </AntApp>
  </ConfigProvider>
);

export default App;
