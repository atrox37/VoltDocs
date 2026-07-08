import { useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { Avatar, Button, Dropdown, Layout, Menu, Typography } from "antd";
import {
  ContainerOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  FundOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  SwapOutlined,
  TeamOutlined,
  TranslationOutlined,
  UserOutlined,
} from "@ant-design/icons";
import type { MenuProps } from "antd";
import type { UserRole } from "../api/auth";
import { hasMinRole, isSuperAdmin, ROLE_LABEL } from "../auth/permissions";
import { useAuth } from "../contexts/AuthContext";
import BrandIcon from "../components/BrandIcon";

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

function buildMenuItems(role: UserRole | undefined): MenuProps["items"] {
  const systemChildren: NonNullable<MenuProps["items"]> = [];

  if (isSuperAdmin(role)) {
    systemChildren.push({ key: "/admin", icon: <TeamOutlined />, label: "用户管理" });
    systemChildren.push({ key: "/quality-dashboard", icon: <FundOutlined />, label: "质量仪表盘" });
  }
  if (hasMinRole(role, "manager")) {
    systemChildren.push({ key: "/audit-logs", icon: <ContainerOutlined />, label: "操作日志" });
  }

  const items: NonNullable<MenuProps["items"]> = [
    {
      type: "group",
      label: "工作流",
      children: [
        { key: "/convert", icon: <SwapOutlined />, label: "文档转换" },
        { key: "/translate", icon: <TranslationOutlined />, label: "文档翻译" },
      ],
    },
    {
      type: "group",
      label: "资产",
      children: [
        { key: "/templates", icon: <FileTextOutlined />, label: "模板中心" },
        { key: "/memory", icon: <DatabaseOutlined />, label: "术语库" },
      ],
    },
  ];

  if (systemChildren.length > 0) {
    items.push({
      type: "group",
      label: "系统",
      children: systemChildren,
    });
  }

  return items;
}

export default function AppLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { user, logout } = useAuth();
  const menuItems = buildMenuItems(user?.role);

  const userMenu: MenuProps["items"] = [
    {
      key: "user-info",
      label: (
        <div style={{ padding: "4px 0" }}>
          <div style={{ fontWeight: 600 }}>{user?.name}</div>
          <div style={{ fontSize: 12, color: "#888" }}>{user?.email}</div>
          {user?.role ? (
            <div style={{ fontSize: 11, color: "#aaa", marginTop: 2 }}>{ROLE_LABEL[user.role]}</div>
          ) : null}
        </div>
      ),
      disabled: true,
    },
    { type: "divider" },
    {
      key: "logout",
      icon: <LogoutOutlined />,
      label: "退出登录",
      danger: true,
      onClick: () => void logout(),
    },
  ];

  const pageTitles: Record<string, { title: string; subtitle: string }> = {
    "/convert": {
      title: "文档转换",
      subtitle: "将 Markdown 文档转换为 Word 文档，统一输出版式。",
    },
    "/translate": {
      title: "文档翻译",
      subtitle: "上传 Word 或 Excel 文档，创建翻译任务并处理 QA 复核。",
    },
    "/templates": {
      title: "模板中心",
      subtitle: "管理 Word 输出模板，统一转换结果的版式和样式。",
    },
    "/memory": {
      title: "术语库",
      subtitle: "维护中英术语对，翻译时按语言方向自动应用。",
    },
    "/admin": {
      title: "用户管理",
      subtitle: "管理用户角色与访问权限。",
    },
    "/quality-dashboard": {
      title: "质量仪表盘",
      subtitle: "集中查看全局 QA 与 TM 运行情况，不再在单文件翻译页展示报表。",
    },
    "/audit-logs": {
      title: "操作日志",
      subtitle: "查看系统内的关键操作记录。",
    },
  };

  const current = pageTitles[pathname] ?? { title: "", subtitle: "" };

  return (
    <Layout style={{ height: "100vh" }}>
      <Sider
        trigger={null}
        collapsible
        collapsed={collapsed}
        width={220}
        collapsedWidth={64}
        style={{ borderRight: "1px solid #f0f0f0" }}
        theme="light"
      >
        <div
          style={{
            height: 64,
            display: "flex",
            alignItems: "center",
            padding: "0 16px",
            borderBottom: "1px solid #f0f0f0",
            gap: 10,
          }}
        >
          <BrandIcon size={32} />
          {!collapsed ? (
            <div style={{ lineHeight: 1.2 }}>
              <div style={{ fontSize: 15, fontWeight: 600, color: "#1b3a6b" }}>VoltDocs</div>
              <div style={{ fontSize: 10, color: "#999", letterSpacing: 1, textTransform: "uppercase" }}>
                Voltage Internal
              </div>
            </div>
          ) : null}
        </div>

        <Menu
          mode="inline"
          selectedKeys={[pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ borderRight: 0, marginTop: 8 }}
        />
      </Sider>

      <Layout>
        <Header
          style={{
            background: "#fff",
            padding: "0 24px",
            display: "flex",
            alignItems: "center",
            borderBottom: "1px solid #f0f0f0",
            height: 64,
            gap: 16,
          }}
        >
          <Button
            type="text"
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setCollapsed(!collapsed)}
            style={{ fontSize: 16 }}
          />

          <div style={{ flex: 1 }} />

          <Dropdown menu={{ items: userMenu }} placement="bottomRight">
            <div style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
              <Avatar size={32} icon={<UserOutlined />} style={{ backgroundColor: "#1b3a6b" }} />
              <span style={{ fontSize: 13 }}>{user?.name}</span>
            </div>
          </Dropdown>
        </Header>

        <Content
          style={{
            overflow: "hidden",
            background: "#f5f7fa",
            display: "flex",
            flexDirection: "column",
            height: "calc(100vh - 64px)",
          }}
        >
          {current.title ? (
            <div style={{ padding: "16px 24px 0", flexShrink: 0 }}>
              <Typography.Title level={4} style={{ marginBottom: 0 }}>
                {current.title}
              </Typography.Title>
              <Text type="secondary" style={{ fontSize: 13 }}>
                {current.subtitle}
              </Text>
            </div>
          ) : null}
          <div
            style={{
              flex: 1,
              overflow: "auto",
              padding: "12px 24px 24px",
              minHeight: 0,
            }}
          >
            <Outlet />
          </div>
        </Content>
      </Layout>
    </Layout>
  );
}
