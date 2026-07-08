import { useEffect, useState } from "react";
import { App, Button, Modal, Select, Table, Tag, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type { UserRole } from "../api/auth";
import { listUsers, updateUserRole, type UserEntry } from "../api/users";
import { ROLE_COLOR, ROLE_LABEL, ROLE_OPTIONS } from "../auth/permissions";
import { useAuth } from "../contexts/AuthContext";

const { Text } = Typography;

export default function Admin() {
  const { notification } = App.useApp();
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<UserEntry[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [updatingRow, setUpdatingRow] = useState<string | null>(null);

  const fetchUsers = async () => {
    setLoadingUsers(true);
    try {
      const data = await listUsers();
      setUsers(data);
    } catch (err: unknown) {
      notification.error({
        message: "Failed to load users",
        description: err instanceof Error ? err.message : "Unknown error",
      });
    } finally {
      setLoadingUsers(false);
    }
  };

  useEffect(() => {
    void fetchUsers();
  }, []);

  const handleRoleChange = (email: string, newRole: UserRole) => {
    const isSelf = currentUser?.email === email;
    const isDowngrade = newRole !== "super_admin";

    const doUpdate = async () => {
      setUpdatingRow(email);
      try {
        await updateUserRole(email, newRole);
        notification.success({
          message: "Role updated",
          description: `${email} is now ${ROLE_LABEL[newRole]}.`,
        });
        await fetchUsers();
      } catch (err: unknown) {
        notification.error({
          message: "Failed to update role",
          description: err instanceof Error ? err.message : "Unknown error",
        });
      } finally {
        setUpdatingRow(null);
      }
    };

    if (isSelf && isDowngrade) {
      Modal.confirm({
        title: "Lower your own role?",
        content: `You are changing your own account to ${ROLE_LABEL[newRole]}. If this is the last super admin account, the backend will reject the change.`,
        okText: "Confirm",
        okButtonProps: { danger: true },
        cancelText: "Cancel",
        onOk: doUpdate,
      });
      return;
    }

    void doUpdate();
  };

  const columns: ColumnsType<UserEntry> = [
    {
      title: "Email",
      dataIndex: "email",
      key: "email",
      ellipsis: true,
    },
    {
      title: "Role",
      dataIndex: "role",
      key: "role",
      width: 130,
      render: (role: UserRole) => (
        <Tag color={ROLE_COLOR[role] ?? "default"}>
          {ROLE_LABEL[role] ?? role}
        </Tag>
      ),
    },
    {
      title: "Last Login",
      dataIndex: "lastLogin",
      key: "lastLogin",
      width: 200,
      render: (value: string | null) => (value ? new Date(value).toLocaleString("zh-CN") : "-"),
    },
    {
      title: "Action",
      key: "actions",
      width: 160,
      render: (_: unknown, record: UserEntry) => (
        <Select<UserRole>
          value={record.role}
          size="small"
          style={{ width: 130 }}
          loading={updatingRow === record.email}
          disabled={updatingRow === record.email}
          onChange={(value) => handleRoleChange(record.email, value)}
          options={ROLE_OPTIONS}
        />
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 16, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Text type="secondary" style={{ fontSize: 13 }}>
          Manage application roles. Super admins can promote or demote other users.
        </Text>
        <Button icon={<ReloadOutlined />} onClick={() => void fetchUsers()} loading={loadingUsers}>
          Refresh
        </Button>
      </div>
      <Table
        rowKey="email"
        dataSource={users}
        columns={columns}
        loading={loadingUsers}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        size="middle"
        locale={{ emptyText: "No users found" }}
      />
    </div>
  );
}
