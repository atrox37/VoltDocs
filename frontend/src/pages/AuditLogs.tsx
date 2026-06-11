import { useEffect, useState } from "react";
import { App, Button, Card, DatePicker, Pagination, Select, Space, Table, Tag, Tooltip, Typography } from "antd";
import { DownloadOutlined, ReloadOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type { RangePickerProps } from "antd/es/date-picker";
import { get } from "@/api/client";

const { Text } = Typography;
const { RangePicker } = DatePicker;

interface AuditLogEntry {
  id: string;
  time: string;
  actor: string;
  action: string;
  details: Record<string, unknown> | null;
}

interface AuditLogsResponse {
  logs: AuditLogEntry[];
  page: number;
  pageSize: number;
  total: number;
}

const ACTION_OPTIONS = [
  { value: "", label: "全部操作" },
  { value: "role_change", label: "角色变更" },
  { value: "create", label: "新增术语" },
  { value: "update", label: "更新术语" },
  { value: "import_create", label: "导入新增" },
  { value: "import_replace", label: "导入替换" },
  { value: "delete", label: "删除术语" },
  { value: "job_created", label: "创建任务" },
];

const ACTION_LABEL: Record<string, string> = {
  role_change: "角色变更",
  create: "新增术语",
  update: "更新术语",
  import_create: "导入新增",
  import_replace: "导入替换",
  delete: "删除术语",
  job_created: "创建任务",
};

const ACTION_COLOR: Record<string, string> = {
  role_change: "volcano",
  create: "green",
  update: "blue",
  import_create: "cyan",
  import_replace: "orange",
  delete: "red",
  job_created: "purple",
};

function tryParse(val: unknown): unknown {
  if (typeof val === "string") {
    try { return JSON.parse(val); } catch { return val; }
  }
  return val;
}

function summarizeDetails(action: string, details: Record<string, unknown> | null): string {
  if (!details) return "—";
  const after = tryParse(details.after) as Record<string, unknown> | null;
  const before = tryParse(details.before) as Record<string, unknown> | null;

  switch (action) {
    case "job_created": {
      const d = (after ?? details) as Record<string, unknown>;
      const fileName = d?.fileName ?? details.fileName;
      const srcLang = d?.sourceLang ?? details.sourceLang ?? "";
      const tgtLang = d?.targetLang ?? details.targetLang ?? "";
      const jobType = d?.jobType ?? details.jobType ?? "";
      if (fileName) return `${jobType ? `[${String(jobType)}] ` : ""}${String(fileName)}  ${String(srcLang)} → ${String(tgtLang)}`;
      return JSON.stringify(details);
    }
    case "role_change": {
      const target = details.targetEmail ?? "";
      const oldR = details.oldRole ?? (before as Record<string, unknown>)?.role ?? "";
      const newR = details.newRole ?? (after as Record<string, unknown>)?.role ?? "";
      return `${String(target)}：${String(oldR)} → ${String(newR)}`;
    }
    case "create":
    case "import_create": {
      const d = (after ?? details) as Record<string, unknown>;
      const src = d?.sourceTerm ?? details.sourceTerm ?? "";
      const tgt = d?.targetTerm ?? details.targetTerm ?? "";
      if (src) return `${String(src)} → ${String(tgt)}`;
      return JSON.stringify(details);
    }
    case "update": {
      const src = (before as Record<string, unknown>)?.source_term
        ?? (after as Record<string, unknown>)?.targetTerm ?? "";
      const oldTgt = (before as Record<string, unknown>)?.target_term ?? "";
      const newTgt = (after as Record<string, unknown>)?.targetTerm ?? "";
      if (src) return `${String(src)}：${String(oldTgt)} → ${String(newTgt)}`;
      return JSON.stringify(details);
    }
    case "import_replace": {
      const d = (after ?? details) as Record<string, unknown>;
      const src = d?.sourceTerm ?? "";
      const tgt = d?.targetTerm ?? "";
      if (src) return `${String(src)} → ${String(tgt)}`;
      return JSON.stringify(details);
    }
    case "delete": {
      const d = (before ?? details) as Record<string, unknown>;
      const src = d?.source_term ?? "";
      const tgt = d?.target_term ?? "";
      if (src) return `${String(src)} → ${String(tgt)}`;
      return JSON.stringify(details);
    }
    default:
      return JSON.stringify(details);
  }
}

export default function AuditLogs() {
  const { notification } = App.useApp();
  const [logs, setLogs] = useState<AuditLogEntry[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [actionFilter, setActionFilter] = useState("");
  const [dateRange, setDateRange] = useState<[string, string] | null>(null);

  const fetchLogs = async (currentPage: number, currentPageSize: number) => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (actionFilter) params.set("action", actionFilter);
      if (dateRange) {
        params.set("from", dateRange[0]);
        params.set("to", dateRange[1]);
      }
      params.set("page", String(currentPage));
      params.set("pageSize", String(currentPageSize));
      const qs = params.toString();
      const data = await get<AuditLogsResponse>(`/audit-logs${qs ? `?${qs}` : ""}`);
      setLogs(data.logs ?? []);
      setTotal(data.total ?? 0);
    } catch (err: unknown) {
      notification.error({
        message: "加载操作日志失败",
        description: err instanceof Error ? err.message : "未知错误",
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchLogs(1, pageSize);
    setPage(1);
  }, [actionFilter, dateRange]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleRangeChange: RangePickerProps["onChange"] = (_, formatStr) => {
    setDateRange(formatStr[0] && formatStr[1] ? [formatStr[0], formatStr[1]] : null);
  };

  const handlePageChange = (nextPage: number, nextPageSize: number) => {
    setPage(nextPage);
    setPageSize(nextPageSize);
    void fetchLogs(nextPage, nextPageSize);
  };

  const columns: ColumnsType<AuditLogEntry> = [
    {
      title: "时间",
      dataIndex: "time",
      key: "time",
      width: 180,
      render: (v: string) => (
        <Text style={{ fontFamily: "monospace", fontSize: 12 }}>
          {new Date(v).toLocaleString("zh-CN")}
        </Text>
      ),
    },
    {
      title: "操作人",
      dataIndex: "actor",
      key: "actor",
      width: 220,
      ellipsis: true,
    },
    {
      title: "操作类型",
      dataIndex: "action",
      key: "action",
      width: 120,
      render: (v: string) => (
        <Tag color={ACTION_COLOR[v] ?? "default"}>{ACTION_LABEL[v] ?? v}</Tag>
      ),
    },
    {
      title: "详情",
      key: "details",
      render: (_: unknown, record: AuditLogEntry) => {
        const summary = summarizeDetails(record.action, record.details);
        const full = record.details ? JSON.stringify(record.details, null, 2) : "—";
        return (
          <Tooltip
            title={
              <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all", maxHeight: 280, overflow: "auto", fontSize: 11 }}>
                {full}
              </pre>
            }
            placement="topLeft"
            overlayStyle={{ maxWidth: 500 }}
          >
            <Text style={{ fontSize: 12, color: "#555", cursor: "default" }} ellipsis>
              {summary}
            </Text>
          </Tooltip>
        );
      },
    },
  ];

  return (
    <Card
      title="操作日志"
      style={{ height: "100%", display: "flex", flexDirection: "column" }}
      styles={{ body: { flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", padding: "12px 16px 8px" } }}
      extra={
        <Space wrap>
          <Select
            value={actionFilter}
            onChange={setActionFilter}
            options={ACTION_OPTIONS}
            style={{ width: 160 }}
            placeholder="筛选操作类型"
          />
          <RangePicker
            onChange={handleRangeChange}
            format="YYYY-MM-DD"
            placeholder={["开始日期", "结束日期"]}
          />
          <Button
            icon={<ReloadOutlined />}
            onClick={() => void fetchLogs(page, pageSize)}
            loading={loading}
          />
          <Button
            icon={<DownloadOutlined />}
            onClick={() => window.open("/api/audit-logs/export-csv", "_blank")}
          >
            导出 CSV
          </Button>
        </Space>
      }
    >
      {/* Table without internal pagination — rows are fixed height (single-line detail) */}
      <Table
        rowKey="id"
        dataSource={logs}
        columns={columns}
        loading={loading}
        size="middle"
        style={{ flex: 1, minHeight: 0 }}
        scroll={{ y: "calc(100vh - 320px)" }}
        pagination={false}
        locale={{ emptyText: "暂无操作日志" }}
      />

      {/* Pagination always visible at the bottom */}
      <div style={{ display: "flex", justifyContent: "flex-end", paddingTop: 10, flexShrink: 0 }}>
        <Pagination
          current={page}
          pageSize={pageSize}
          total={total}
          showSizeChanger
          pageSizeOptions={[10, 20, 50, 100]}
          showTotal={(t) => `共 ${t} 条`}
          size="small"
          onChange={handlePageChange}
          onShowSizeChange={handlePageChange}
        />
      </div>
    </Card>
  );
}
