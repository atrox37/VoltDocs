import { useEffect, useState } from "react";
import {
  App,
  Table,
  Tag,
  Select,
  Button,
  Modal,
  notification,
  Typography,
  Space,
} from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { listUsers, updateUserRole, type UserEntry } from "../api/users";
import type { UserRole } from "../api/auth";
import { ROLE_COLOR, ROLE_LABEL, ROLE_OPTIONS } from "../auth/permissions";
import { useAuth } from "../contexts/AuthContext";

const { Text } = Typography;

export default function Admin() {
  const { notification: notif } = App.useApp();
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
      notif.error({
        message: "加载用户列表失败",
        description: err instanceof Error ? err.message : "未知错误",
      });
    } finally {
      setLoadingUsers(false);
    }
  };

  useEffect(() => { fetchUsers(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleRoleChange = (email: string, newRole: UserRole) => {
    const isSelf = currentUser?.email === email;
    const isDowngrade = newRole !== "super_admin";

    const doUpdate = async () => {
      setUpdatingRow(email);
      try {
        await updateUserRole(email, newRole);
        notif.success({
          message: "角色已更新",
          description: `${email} 的角色已更改为「${ROLE_LABEL[newRole]}」`,
        });
        await fetchUsers();
      } catch (err: unknown) {
        notif.error({
          message: "角色更新失败",
          description: err instanceof Error ? err.message : "未知错误",
        });
      } finally {
        setUpdatingRow(null);
      }
    };

    if (isSelf && isDowngrade) {
      Modal.confirm({
        title: "降低自己的权限",
        content: `您正在将自己从「超级管理员」降级为「${ROLE_LABEL[newRole]}」。降级后将失去用户管理权限，且如果您是最后一名超级管理员，系统将拒绝此操作。确定要继续吗？`,
        okText: "确认降级",
        okButtonProps: { danger: true },
        cancelText: "取消",
        onOk: doUpdate,
      });
    } else {
      doUpdate();
    }
  };

  const columns: ColumnsType<UserEntry> = [
    {
      title: "邮箱",
      dataIndex: "email",
      key: "email",
      ellipsis: true,
    },
    {
      title: "角色",
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
      title: "最后登录",
      dataIndex: "lastLogin",
      key: "lastLogin",
      width: 200,
      render: (v: string | null) =>
        v ? new Date(v).toLocaleString("zh-CN") : "—",
    },
    {
      title: "操作",
      key: "actions",
      width: 160,
      render: (_: unknown, record: UserEntry) => (
        <Select<UserRole>
          value={record.role}
          size="small"
          style={{ width: 130 }}
          loading={updatingRow === record.email}
          disabled={updatingRow === record.email}
          onChange={(val) => handleRoleChange(record.email, val)}
          options={ROLE_OPTIONS}
        />
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 16, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Text type="secondary" style={{ fontSize: 13 }}>
          管理系统用户的角色与权限。超级管理员可以提升或降低其他用户的权限级别。
        </Text>
        <Button icon={<ReloadOutlined />} onClick={fetchUsers} loading={loadingUsers}>
          刷新
        </Button>
      </div>
      <Table
        rowKey="email"
        dataSource={users}
        columns={columns}
        loading={loadingUsers}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        size="middle"
        locale={{ emptyText: "暂无用户记录" }}
      />
    </div>
  );
}
