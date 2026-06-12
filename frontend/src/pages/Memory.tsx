import { useEffect, useMemo, useState } from "react";
import {
  App,
  Button,
  Card,
  Col,
  Form,
  Input,
  Modal,
  Popconfirm,
  Row,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
  Typography,
  Upload,
} from "antd";
import {
  BookOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  PlusOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type { RcFile } from "antd/es/upload";
import {
  commitGlossaryImport,
  createTerm,
  deleteTerm,
  getTermHitCounts,
  listTerms,
  previewGlossaryImport,
  updateTerm,
  type GlossaryImportPreviewRow,
  type GlossaryTerm,
} from "@/api/glossary";


const { Text, Paragraph } = Typography;

export default function Memory() {
  const { message } = App.useApp();
  const [terms, setTerms] = useState<GlossaryTerm[]>([]);
  const [loading, setLoading] = useState(true);
  const [hitCounts, setHitCounts] = useState<Record<string, number>>({});
  const [searchText, setSearchText] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [editingTerm, setEditingTerm] = useState<GlossaryTerm | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [importPreviewRows, setImportPreviewRows] = useState<GlossaryImportPreviewRow[]>([]);
  const [importSummary, setImportSummary] = useState({ total: 0, create: 0, replace: 0, skip: 0 });
  const [importFileName, setImportFileName] = useState("");
  const [form] = Form.useForm();
  const [editForm] = Form.useForm();
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });

  const fetchTerms = async (q?: string) => {
    setLoading(true);
    try {
      const query = (q ?? searchText).trim();
      const { terms: data } = await listTerms(query ? { q: query } : undefined);
      setTerms(data);
      // Load hit counts in background (non-blocking)
      getTermHitCounts()
        .then(({ hitCounts: counts }) => setHitCounts(counts))
        .catch(() => {/* ignore */});
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : "术语库加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchTerms();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const filteredTerms = useMemo(() => terms, [terms]);

  const handleAdd = async () => {
    try {
      const values = await form.validateFields();
      await createTerm({
        sourceTerm: values.sourceTerm.trim(),
        targetTerm: values.targetTerm.trim(),
        sourceLang: "zh-CN",
        targetLang: "en-US",
        enabled: values.enabled ?? true,
      });
      message.success("术语已新增");
      setShowAdd(false);
      form.resetFields();
      void fetchTerms();
    } catch {
      return;
    }
  };

  const handleEdit = async () => {
    if (!editingTerm) return;
    try {
      const values = await editForm.validateFields();
      await updateTerm(editingTerm.id, {
        targetTerm: values.targetTerm?.trim(),
        enabled: values.enabled,
      });
      message.success("术语已更新");
      setEditingTerm(null);
      void fetchTerms();
    } catch {
      return;
    }
  };

  const handleToggleEnabled = async (id: string, enabled: boolean) => {
    setTogglingId(id);
    try {
      await updateTerm(id, { enabled });
      setTerms((prev) => prev.map((item) => (item.id === id ? { ...item, enabled } : item)));
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : "更新失败");
    } finally {
      setTogglingId(null);
    }
  };

  const handleDelete = async (id: string) => {
    await deleteTerm(id);
    message.success("术语已删除");
    setTerms((prev) => prev.filter((item) => item.id !== id));
  };

  const resetImportState = () => {
    setImportPreviewRows([]);
    setImportSummary({ total: 0, create: 0, replace: 0, skip: 0 });
    setImportFileName("");
  };

  const handleImportPreview = async (file: RcFile) => {
    setPreviewing(true);
    try {
      const result = await previewGlossaryImport(file);
      setImportPreviewRows(result.rows);
      setImportSummary(result.summary);
      setImportFileName(file.name);
      setImportOpen(true);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : "术语表预览失败");
    } finally {
      setPreviewing(false);
    }
    return false;
  };

  const handleImportCommit = async () => {
    setImporting(true);
    try {
      const result = await commitGlossaryImport(importPreviewRows);
      message.success(`导入完成：新增 ${result.summary.create} 条，替换 ${result.summary.replace} 条`);
      setImportOpen(false);
      resetImportState();
      void fetchTerms();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : "术语表导入失败");
    } finally {
      setImporting(false);
    }
  };

  const termColumns: ColumnsType<GlossaryTerm> = [
    {
      title: "中文术语",
      dataIndex: "sourceTerm",
      key: "sourceTerm",
      width: "32%",
      render: (text: string) => <Text strong>{text}</Text>,
    },
    {
      title: "英文术语",
      dataIndex: "targetTerm",
      key: "targetTerm",
      width: "32%",
    },
    {
      title: "命中次数",
      key: "hitCount",
      width: 100,
      align: "center" as const,
      sorter: (a: GlossaryTerm, b: GlossaryTerm) => (hitCounts[a.id] ?? 0) - (hitCounts[b.id] ?? 0),
      render: (_: unknown, record: GlossaryTerm) => {
        const count = hitCounts[record.id] ?? 0;
        return (
          <Text
            style={{ fontFamily: "monospace", color: count > 0 ? "#1b3a6b" : "#ccc" }}
          >
            {count > 0 ? count : "—"}
          </Text>
        );
      },
    },
    {
      title: "是否可用",
      dataIndex: "enabled",
      key: "enabled",
      width: 90,
      align: "center" as const,
      render: (enabled: boolean, record: GlossaryTerm) => (
        <Switch
          size="small"
          checked={enabled}
          loading={togglingId === record.id}
          onChange={(checked) => void handleToggleEnabled(record.id, checked)}
        />
      ),
    },
    {
      title: "操作",
      key: "action",
      width: 90,
      render: (_value, record) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => {
              setEditingTerm(record);
              editForm.setFieldsValue({
                sourceTerm: record.sourceTerm,
                targetTerm: record.targetTerm,
                enabled: record.enabled,
              });
            }}
          />
          <Popconfirm title="确认删除这个术语？" onConfirm={() => void handleDelete(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const previewColumns: ColumnsType<GlossaryImportPreviewRow> = [
    {
      title: "动作",
      dataIndex: "action",
      key: "action",
      width: 90,
      render: (value: GlossaryImportPreviewRow["action"]) => {
        if (value === "create") return <Tag color="green">新增</Tag>;
        if (value === "replace") return <Tag color="orange">替换</Tag>;
        return <Tag>跳过</Tag>;
      },
    },
    {
      title: "中文术语",
      dataIndex: "sourceTerm",
      key: "sourceTerm",
      width: "28%",
    },
    {
      title: "导入后的英文术语",
      dataIndex: "targetTerm",
      key: "targetTerm",
      width: "28%",
    },
    {
      title: "当前已有英文术语",
      dataIndex: "existingTargetTerm",
      key: "existingTargetTerm",
      render: (value?: string) => value || "-",
    },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 170px)", gap: 12 }}>
      <Row gutter={12}>
        <Col span={8}>
          <Card size="small">
            <Statistic title="术语总数" value={terms.length} prefix={<DatabaseOutlined />} />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic title="当前可用" value={terms.filter((item) => item.enabled).length} prefix={<BookOutlined />} />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic title="当前语对" value="中文 ⇄ English" valueStyle={{ fontSize: 14 }} />
          </Card>
        </Col>
      </Row>

      <Card
        size="small"
        style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}
        styles={{ body: { flex: 1, padding: 0, display: "flex", flexDirection: "column", overflow: "hidden" } }}
        title="术语库"
        extra={
          <Space>
            <Input.Search
              placeholder="搜索中文术语或英文术语"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onSearch={(value) => void fetchTerms(value)}
              style={{ width: 240 }}
              allowClear
            />
            <Upload
              accept=".xlsx,.csv"
              showUploadList={false}
              beforeUpload={(file) => {
                void handleImportPreview(file);
                return false;
              }}
            >
              <Button icon={<UploadOutlined />} loading={previewing}>
                批量导入
              </Button>
            </Upload>
            <Button
              icon={<DownloadOutlined />}
              onClick={() => window.open("/api/glossary/export-csv", "_blank")}
            >
              导出
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setShowAdd(true)}>
              新增术语
            </Button>
          </Space>
        }
      >
        <div style={{ padding: "12px 16px 0" }}>
          <Paragraph type="secondary" style={{ marginBottom: 12 }}>
            这是一套可双向使用的中英术语对。翻译时会根据当前方向自动使用同一套术语，无需分别维护两份。
            可通过“是否可用”控制某个术语是否参与翻译。批量导入支持 <Text code>.xlsx</Text> 和 <Text code>.csv</Text>。
          </Paragraph>
        </div>
        <Table
          loading={loading}
          columns={termColumns}
          dataSource={filteredTerms}
          rowKey="id"
          size="small"
          pagination={{
            ...pagination,
            total: filteredTerms.length,
            showSizeChanger: true,
            pageSizeOptions: ["15", "20", "50", "100"],
            showTotal: (total) => `共 ${total} 条`,
            onChange: (page, pageSize) => setPagination({ current: page, pageSize }),
          }}
          scroll={{ y: "calc(100vh - 450px)" }}
        />
      </Card>

      <Modal title="新增术语" open={showAdd} onOk={() => void handleAdd()} onCancel={() => setShowAdd(false)} okText="添加" width={480}>
        <Form form={form} layout="vertical" style={{ marginTop: 16 }} initialValues={{ enabled: true }}>
          <Form.Item name="sourceTerm" label="中文术语" rules={[{ required: true, message: "请输入中文术语" }]}>
            <Input placeholder="例如：太阳能支架" />
          </Form.Item>
          <Form.Item name="targetTerm" label="英文术语" rules={[{ required: true, message: "请输入英文术语" }]}>
            <Input placeholder="例如：solar mounting bracket" />
          </Form.Item>
          <Form.Item name="enabled" label="是否可用" valuePropName="checked">
            <Switch checkedChildren="可用" unCheckedChildren="停用" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="编辑术语" open={!!editingTerm} onOk={() => void handleEdit()} onCancel={() => setEditingTerm(null)} okText="保存" width={480}>
        <Form form={editForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="sourceTerm" label="中文术语">
            <Input disabled />
          </Form.Item>
          <Form.Item name="targetTerm" label="英文术语" rules={[{ required: true, message: "请输入英文术语" }]}>
            <Input />
          </Form.Item>
          <Form.Item name="enabled" label="是否可用" valuePropName="checked">
            <Switch checkedChildren="可用" unCheckedChildren="停用" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="批量导入术语表"
        open={importOpen}
        width={920}
        okText="确认导入"
        cancelText="取消"
        onOk={() => void handleImportCommit()}
        onCancel={() => {
          setImportOpen(false);
          resetImportState();
        }}
        confirmLoading={importing}
      >
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Text>
            文件：<Text strong>{importFileName || "-"}</Text>
          </Text>
          <Space size="large">
            <Tag color="green">新增 {importSummary.create}</Tag>
            <Tag color="orange">替换 {importSummary.replace}</Tag>
            <Tag>跳过 {importSummary.skip}</Tag>
          </Space>
          <Text type="secondary">系统会按“中文术语”匹配已有记录。标记为“替换”的内容会覆盖当前英文术语，请确认后再导入。</Text>
          <Table
            columns={previewColumns}
            dataSource={importPreviewRows}
            rowKey={(record) => `${record.sourceLang}-${record.targetLang}-${record.sourceTerm}`}
            size="small"
            pagination={{ pageSize: 10 }}
          />
        </Space>
      </Modal>
    </div>
  );
}
