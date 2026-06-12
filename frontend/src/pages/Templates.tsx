import { useEffect, useState } from "react";
import {
  App,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
} from "antd";
import {
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  InboxOutlined,
  PlusOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import type { RcFile } from "antd/es/upload";
import {
  deleteTemplate,
  getDownloadUrl,
  listTemplates,
  updateTemplate,
  uploadTemplate,
  type Template,
} from "@/api/templates";

const { Text, Paragraph } = Typography;
const { Dragger } = Upload;

const LANGUAGE_OPTIONS = [
  { value: "zh-CN", label: "简体中文" },
  { value: "en-US", label: "English" },
  { value: "ja-JP", label: "日本語" },
  { value: "de-DE", label: "Deutsch" },
  { value: "fr-FR", label: "Français" },
];

// ─── Add Template Modal ───────────────────────────────────────────────────────

function AddTemplateModal({
  open,
  onClose,
  onAdded,
}: {
  open: boolean;
  onClose: () => void;
  onAdded: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [uploading, setUploading] = useState(false);
  const [pickedFile, setPickedFile] = useState<File | null>(null);

  const handleClose = () => {
    form.resetFields();
    setPickedFile(null);
    onClose();
  };

  const handleBeforeUpload = (f: RcFile) => {
    if (!f.name.endsWith(".docx")) {
      message.warning("仅支持 .docx 格式的模板文件");
      return Upload.LIST_IGNORE;
    }
    setPickedFile(f);
    return false;
  };

  const handleSubmit = async () => {
    if (!pickedFile) {
      message.warning("请先选择一个 .docx 模板文件");
      return;
    }
    try {
      const values = await form.validateFields();
      setUploading(true);
      const tagStr = (values.tags as string[] | undefined)?.join(",") ?? "";
      await uploadTemplate(pickedFile, values.language ?? undefined, tagStr);
      message.success(`模板已添加：${pickedFile.name}`);
      handleClose();
      onAdded();
    } catch (err: unknown) {
      if (err && typeof err === "object" && "errorFields" in err) return;
      message.error(err instanceof Error ? err.message : "模板添加失败");
    } finally {
      setUploading(false);
    }
  };

  return (
    <Modal
      open={open}
      title="新增模板"
      onCancel={handleClose}
      onOk={handleSubmit}
      okText="确认添加"
      cancelText="取消"
      confirmLoading={uploading}
      width={540}
      destroyOnClose
    >
      <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
        <Form.Item label="模板文件" required>
          <Dragger
            accept=".docx"
            maxCount={1}
            fileList={pickedFile ? [{ uid: "1", name: pickedFile.name, status: "done" }] : []}
            beforeUpload={handleBeforeUpload}
            onRemove={() => setPickedFile(null)}
          >
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text">点击或拖入 .docx 模板文件</p>
            <p className="ant-upload-hint">仅支持 Word (.docx) 格式</p>
          </Dragger>
        </Form.Item>
        <Form.Item name="language" label="适用语言">
          <Select allowClear placeholder="选择模板适用的语言（可选）" options={LANGUAGE_OPTIONS} />
        </Form.Item>
        <Form.Item name="tags" label="标签">
          <Select
            mode="tags"
            placeholder="输入标签后按 Enter 确认，可多个（可选）"
            tokenSeparators={[","]}
            open={false}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ─── Edit Template Modal ──────────────────────────────────────────────────────

function EditTemplateModal({
  template,
  onClose,
  onSaved,
}: {
  template: Template | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  // Populate form when template changes
  useEffect(() => {
    if (template) {
      let tags: string[] = [];
      try { tags = JSON.parse(template.tags || "[]"); } catch { /* ignore */ }
      form.setFieldsValue({ language: template.language ?? undefined, tags });
    }
  }, [template, form]);

  const handleClose = () => {
    form.resetFields();
    onClose();
  };

  const handleSubmit = async () => {
    if (!template) return;
    try {
      const values = await form.validateFields();
      setSaving(true);
      await updateTemplate(template.id, {
        language: values.language ?? null,
        tags: values.tags ?? [],
      });
      message.success("模板信息已更新");
      handleClose();
      onSaved();
    } catch (err: unknown) {
      if (err && typeof err === "object" && "errorFields" in err) return;
      message.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={!!template}
      title={`编辑模板：${template?.fileName ?? ""}`}
      onCancel={handleClose}
      onOk={handleSubmit}
      okText="保存"
      cancelText="取消"
      confirmLoading={saving}
      width={480}
      destroyOnClose
    >
      <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
        <Form.Item name="language" label="适用语言">
          <Select allowClear placeholder="选择模板适用的语言（可选）" options={LANGUAGE_OPTIONS} />
        </Form.Item>
        <Form.Item name="tags" label="标签">
          <Select
            mode="tags"
            placeholder="输入标签后按 Enter 确认，可多个（可选）"
            tokenSeparators={[","]}
            open={false}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ─── Templates page ───────────────────────────────────────────────────────────

export default function Templates() {
  const { message } = App.useApp();
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<Template | null>(null);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const { templates: data } = await listTemplates();
      setTemplates(data);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : "模板列表加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void fetchAll(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleDelete = async (id: string) => {
    await deleteTemplate(id);
    message.success("模板已删除");
    setTemplates((prev) => prev.filter((item) => item.id !== id));
  };

  const handleDownload = (template: Template) => {
    const a = document.createElement("a");
    a.href = getDownloadUrl(template.fileId);
    a.download = template.fileName;
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  const filtered = searchText
    ? templates.filter((item) => item.fileName.toLowerCase().includes(searchText.toLowerCase()))
    : templates;

  const columns = [
    {
      title: "模板名称",
      dataIndex: "fileName",
      key: "fileName",
      render: (name: string) => <Text strong>{name}</Text>,
    },
    {
      title: "语言",
      dataIndex: "language",
      key: "language",
      width: 130,
      render: (value?: string) => {
        if (!value) return <Text type="secondary">—</Text>;
        const opt = LANGUAGE_OPTIONS.find((o) => o.value === value);
        return <Tag>{opt?.label ?? value}</Tag>;
      },
    },
    {
      title: "标签",
      dataIndex: "tags",
      key: "tags",
      render: (tags: string) => {
        try {
          const values: string[] = JSON.parse(tags || "[]");
          if (!values.length) return <Text type="secondary">—</Text>;
          return <Space size={4}>{values.map((v) => <Tag key={v}>{v}</Tag>)}</Space>;
        } catch {
          return <Text type="secondary">—</Text>;
        }
      },
    },
    {
      title: "上传时间",
      dataIndex: "createdAt",
      key: "createdAt",
      width: 160,
      render: (value: string) => new Date(value).toLocaleString("zh-CN"),
    },
    {
      title: "操作",
      key: "action",
      width: 240,
      render: (_: unknown, record: Template) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => setEditingTemplate(record)}
          >
            编辑
          </Button>
          <Button
            type="link"
            size="small"
            icon={<DownloadOutlined />}
            onClick={() => handleDownload(record)}
          >
            下载
          </Button>
          <Popconfirm title="确认删除这个模板？" onConfirm={() => void handleDelete(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Card
        title="模板列表"
        style={{ height: "100%", display: "flex", flexDirection: "column" }}
        styles={{ body: { flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", padding: "16px 24px 0" } }}
        extra={
          <Space>
            <Input
              prefix={<SearchOutlined />}
              placeholder="搜索模板名称"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              style={{ width: 220 }}
              allowClear
            />
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setShowAdd(true)}>
              新增模板
            </Button>
          </Space>
        }
      >
        <Paragraph type="secondary" style={{ marginBottom: 12, flexShrink: 0 }}>
          模板用于控制 <Text code>.md → Word</Text> 输出时的样式、标题层级和页面结构。建议上传已整理好的标准 Word 模板。
        </Paragraph>
        {/* flex:1 + overflow:hidden makes the table container fill remaining space */}
        <div style={{ flex: 1, overflow: "hidden" }}>
          <Table
            loading={loading}
            columns={columns}
            dataSource={filtered}
            rowKey="id"
            size="middle"
            /* sticky keeps the header fixed; scroll.y makes the body scroll */
            sticky
            scroll={{ y: "calc(100vh - 360px)" }}
            pagination={{ pageSize: 20, showSizeChanger: false }}
            locale={{ emptyText: '暂无模板，点击"新增模板"添加' }}
          />
        </div>
      </Card>

      <AddTemplateModal
        open={showAdd}
        onClose={() => setShowAdd(false)}
        onAdded={() => void fetchAll()}
      />

      <EditTemplateModal
        template={editingTemplate}
        onClose={() => setEditingTemplate(null)}
        onSaved={() => void fetchAll()}
      />
    </>
  );
}
