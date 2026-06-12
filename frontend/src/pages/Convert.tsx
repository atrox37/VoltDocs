import { useEffect, useState } from "react";
import {
  App,
  Button,
  Card,
  Divider,
  Input,
  Modal,
  Progress,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
} from "antd";
import {
  CheckCircleOutlined,
  DownloadOutlined,
  FileTextOutlined,
  InboxOutlined,
  LoadingOutlined,
} from "@ant-design/icons";
import type { RcFile, UploadFile } from "antd/es/upload";
import { createConvertJob, getConvertJob, getConvertProgress } from "@/api/convert";
import { listTemplates, type Template } from "@/api/templates";

const { Dragger } = Upload;
const { Text, Paragraph } = Typography;

export default function Convert() {
  const { message } = App.useApp();
  const [file, setFile] = useState<File | null>(null);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [converting, setConverting] = useState(false);
  const [progress, setProgress] = useState(0);
  const [outputFileName, setOutputFileName] = useState("");
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const [showTemplatePicker, setShowTemplatePicker] = useState(false);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);

  const loadTemplates = async () => {
    setTemplatesLoading(true);
    try {
      const { templates: data } = await listTemplates();
      setTemplates(data);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : "模板列表加载失败");
    } finally {
      setTemplatesLoading(false);
    }
  };

  useEffect(() => {
    if (showTemplatePicker) void loadTemplates();
  }, [showTemplatePicker]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleBeforeUpload = (f: RcFile) => {
    const ext = f.name.split(".").pop()?.toLowerCase();
    if (ext !== "md") {
      message.warning("仅接受 .md 文件");
      return Upload.LIST_IGNORE;
    }
    setFile(f);
    setFileList([{ uid: "1", name: f.name, status: "done", size: f.size }]);
    return false;
  };

  const startConvert = async () => {
    if (!file) return;
    setConverting(true);
    setProgress(0);
    try {
      const { id: jobId } = await createConvertJob(
        file,
        "docx",
        selectedTemplate?.id || undefined,
        outputFileName.trim() || undefined
      );
      const poll = setInterval(async () => {
        try {
          const { status, progress: nextProgress } = await getConvertProgress(jobId);
          setProgress(nextProgress);
          if (status === "succeeded") {
            clearInterval(poll);
            setConverting(false);
            const job = await getConvertJob(jobId);
            if (job.result?.fileId) {
              const a = document.createElement("a");
              a.href = `/api/files/${job.result.fileId}/download`;
              a.download = outputFileName.trim() || job.result.fileName || "converted";
              document.body.appendChild(a);
              a.click();
              a.remove();
              message.success(`转换完成，已开始下载 ${a.download}`);
            }
          } else if (status === "failed") {
            clearInterval(poll);
            setConverting(false);
            const job = await getConvertJob(jobId);
            message.error(`转换失败：${job.errorMessage || "未知错误"}`);
          }
        } catch { return; }
      }, 1000);
    } catch (err: unknown) {
      setConverting(false);
      message.error(err instanceof Error ? err.message : "转换任务提交失败");
    }
  };

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto" }}>
      <div style={{ display: "flex", gap: 24, alignItems: "flex-start" }}>
        {/* Left: upload */}
        <div style={{ flex: 1 }}>
          <Card>
            <Dragger
              accept=".md"
              maxCount={1}
              fileList={fileList}
              beforeUpload={handleBeforeUpload}
              onRemove={() => { setFile(null); setFileList([]); }}
              openFileDialogOnClick
            >
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p className="ant-upload-text">点击或拖入待转换的 .md 文件</p>
              <p className="ant-upload-hint">将 Markdown 文件转换为 Word 文档，可套用公司模板输出</p>
            </Dragger>
          </Card>
        </div>

        {/* Right: settings + action */}
        <Card style={{ width: 280, flexShrink: 0 }}>
          <Space direction="vertical" style={{ width: "100%" }} size="middle">
            <div>
              <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 4 }}>
                输出文件名（留空使用原文件名）
              </Text>
              <Input
                value={outputFileName}
                onChange={(e) => setOutputFileName(e.target.value)}
                placeholder="例：output.docx"
                size="small"
              />
            </div>

            <div>
              <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 4 }}>
                Word 模板
              </Text>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                {selectedTemplate ? (
                  <Tag
                    icon={<CheckCircleOutlined />}
                    color="blue"
                    closable
                    onClose={() => setSelectedTemplate(null)}
                    style={{ fontSize: 12, padding: "2px 8px" }}
                  >
                    {selectedTemplate.fileName}
                  </Tag>
                ) : (
                  <Text type="secondary" style={{ fontSize: 12 }}>未选择模板</Text>
                )}
                <Button size="small" icon={<FileTextOutlined />} onClick={() => setShowTemplatePicker(true)}>
                  {selectedTemplate ? "更换" : "选择"}
                </Button>
              </div>
            </div>

            <Divider style={{ margin: "4px 0" }} />

            <div>
              <Text strong style={{ fontSize: 13 }}>.md → Word</Text>
              <Paragraph type="secondary" style={{ marginTop: 4, marginBottom: 12, fontSize: 12 }}>
                将 Markdown 文件转换为可交付的 Word 文档，适合把手册、说明、知识库文稿整理为标准格式输出。
              </Paragraph>

              {converting && (
                <div style={{ marginBottom: 12 }}>
                  <Space align="center" style={{ marginBottom: 4 }}>
                    <LoadingOutlined />
                    <Text style={{ fontSize: 12 }}>正在转换 {progress}%</Text>
                  </Space>
                  <Progress percent={progress} size="small" />
                </div>
              )}

              <Button
                type="primary"
                icon={converting ? <LoadingOutlined /> : <DownloadOutlined />}
                block
                size="large"
                disabled={!file || converting}
                onClick={startConvert}
              >
                {converting ? "转换中" : "转换并下载 Word"}
              </Button>
              <Text type="secondary" style={{ fontSize: 11, display: "block", textAlign: "center", marginTop: 6 }}>
                转换成功后自动下载
              </Text>
            </div>
          </Space>
        </Card>
      </div>

      {/* Template picker modal */}
      <Modal
        title="选择 Word 模板"
        open={showTemplatePicker}
        onCancel={() => setShowTemplatePicker(false)}
        footer={null}
        width={640}
      >
        <Paragraph type="secondary" style={{ marginBottom: 12, fontSize: 12 }}>
          模板会影响导出 Word 的段落样式、标题结构和页面观感。如需新增模板，请前往"模板中心"上传。
        </Paragraph>
        <Table
          loading={templatesLoading}
          dataSource={templates}
          rowKey="id"
          size="small"
          pagination={false}
          scroll={{ y: 320 }}
          columns={[
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
              width: 120,
              render: (value?: string) => value || "-",
            },
            {
              title: "上传时间",
              dataIndex: "createdAt",
              key: "createdAt",
              width: 140,
              render: (value: string) => new Date(value).toLocaleDateString("zh-CN"),
            },
            {
              title: "操作",
              key: "action",
              width: 80,
              render: (_: unknown, record: Template) => (
                <Button
                  type="link"
                  size="small"
                  onClick={() => {
                    setSelectedTemplate(record);
                    setShowTemplatePicker(false);
                    message.success(`已选择模板：${record.fileName}`);
                  }}
                >
                  使用
                </Button>
              ),
            },
          ]}
          locale={{ emptyText: '暂无模板，请前往"模板中心"上传' }}
        />
      </Modal>
    </div>
  );
}
