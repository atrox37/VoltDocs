import { useEffect, useState } from "react";
import {
  App,
  Button,
  Card,
  Input,
  Modal,
  Progress,
  Select,
  Segmented,
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
  SettingOutlined,
} from "@ant-design/icons";
import type { RcFile, UploadFile } from "antd/es/upload";
import { createConvertJob, getConvertJob, getConvertProgress } from "@/api/convert";
import { listTemplates, type Template } from "@/api/templates";

const { Dragger } = Upload;
const { Text, Paragraph } = Typography;

type Direction = "md2docx" | "docx2md";

export default function Convert() {
  const { message } = App.useApp();
  const [direction, setDirection] = useState<Direction>("md2docx");
  const [file, setFile] = useState<File | null>(null);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [converting, setConverting] = useState(false);
  const [progress, setProgress] = useState(0);
  const [outputFileName, setOutputFileName] = useState("");
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const [showTemplatePicker, setShowTemplatePicker] = useState(false);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);

  const isMd = direction === "md2docx";
  const acceptTypes = isMd ? ".md" : ".docx";

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
    if (showTemplatePicker) {
      void loadTemplates();
    }
  }, [showTemplatePicker]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleBeforeUpload = (f: RcFile) => {
    const ext = f.name.split(".").pop()?.toLowerCase();
    if (isMd) {
      if (ext !== "md") {
        message.warning("当前模式仅接受 .md 文件");
        return Upload.LIST_IGNORE;
      }
    } else if (ext !== "docx") {
      message.warning("当前模式仅接受 .docx 文件");
      return Upload.LIST_IGNORE;
    }

    setFile(f);
    setFileList([{ uid: "1", name: f.name, status: "done", size: f.size }]);
    return false;
  };

  const handleDirectionChange = (value: string) => {
    setDirection(value as Direction);
    setFile(null);
    setFileList([]);
    setProgress(0);
    setOutputFileName("");
    setSelectedTemplate(null);
  };

  const startConvert = async () => {
    if (!file) return;
    setConverting(true);
    setProgress(0);
    try {
      const { id: jobId } = await createConvertJob(
        file,
        isMd ? "docx" : "md",
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
        } catch {
          return;
        }
      }, 1000);
    } catch (err: unknown) {
      setConverting(false);
      message.error(err instanceof Error ? err.message : "转换任务提交失败");
    }
  };

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto" }}>
      <Segmented
        value={direction}
        onChange={handleDirectionChange}
        options={[
          { label: ".md -> Word", value: "md2docx" },
          { label: "Word -> .md", value: "docx2md" },
        ]}
        style={{ marginBottom: 20 }}
        size="large"
      />

      <div style={{ display: "flex", gap: 24, alignItems: "flex-start" }}>
        <div style={{ flex: 1 }}>
          <Card style={{ marginBottom: 16 }}>
            <Dragger
              accept={acceptTypes}
              maxCount={1}
              fileList={fileList}
              beforeUpload={handleBeforeUpload}
              onRemove={() => {
                setFile(null);
                setFileList([]);
              }}
              openFileDialogOnClick
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">
                {isMd ? "点击或拖入待转换的 .md 文件" : "点击或拖入待转换的 .docx 文件"}
              </p>
              <p className="ant-upload-hint">
                {isMd
                  ? "当前会把 .md 转成 Word 文档，可套用模板输出"
                  : "当前会把 Word 文档转成 .md 文本，适合整理文档内容"}
              </p>
            </Dragger>
          </Card>

          <Card title={<><SettingOutlined /> 转换设置</>} size="small">
            <Space direction="vertical" style={{ width: "100%" }} size="middle">
              <div>
                <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 4 }}>
                  输出文件名
                </Text>
                <Input
                  value={outputFileName}
                  onChange={(e) => setOutputFileName(e.target.value)}
                  placeholder={isMd ? "例如：installation-guide.docx" : "例如：installation-guide.md"}
                />
              </div>

              {isMd && (
                <div>
                  <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 4 }}>
                    Word 模板
                  </Text>
                  <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
                    如果希望导出的 Word 保持公司样式、标题层级和页面结构，可以选择一个模板。未选择时将使用默认样式输出。
                  </Paragraph>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    {selectedTemplate ? (
                      <Tag
                        icon={<CheckCircleOutlined />}
                        color="blue"
                        closable
                        onClose={() => setSelectedTemplate(null)}
                        style={{ fontSize: 13, padding: "4px 10px" }}
                      >
                        {selectedTemplate.fileName}
                      </Tag>
                    ) : (
                      <Text type="secondary" style={{ fontSize: 13 }}>
                        未选择模板
                      </Text>
                    )}
                    <Button size="small" icon={<FileTextOutlined />} onClick={() => setShowTemplatePicker(true)}>
                      {selectedTemplate ? "更换模板" : "选择模板"}
                    </Button>
                  </div>
                </div>
              )}

              {!isMd && (
                <Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 12 }}>
                  Word 转 .md 时会尽量保留标题层级、段落顺序和表格文本内容，复杂样式会做合理简化。
                </Paragraph>
              )}
            </Space>
          </Card>
        </div>

        <Card title="转换方向" style={{ width: 260, flexShrink: 0 }}>
          <Space direction="vertical" style={{ width: "100%" }} size="middle">
            <div>
              <Text strong>{isMd ? ".md → Word" : "Word → .md"}</Text>
              <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }}>
                {isMd
                  ? "适合把手册、说明、知识库文稿整理为可交付的 Word 文件。"
                  : "适合把现有 Word 文档整理为便于编辑、比对和版本管理的 .md 文件。"}
              </Paragraph>
            </div>

            {converting && (
              <div>
                <Space align="center" style={{ marginBottom: 4 }}>
                  <LoadingOutlined />
                  <Text>正在转换</Text>
                  <Text type="secondary">{progress}%</Text>
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
              {converting ? "转换中" : isMd ? "转换并下载 Word" : "转换并下载 .md"}
            </Button>

            <Text type="secondary" style={{ fontSize: 12 }}>
              转换成功后会自动开始下载。
            </Text>
          </Space>
        </Card>
      </div>

      <Modal
        title="选择 Word 模板"
        open={showTemplatePicker}
        onCancel={() => setShowTemplatePicker(false)}
        footer={null}
        width={640}
      >
        <Paragraph type="secondary" style={{ marginBottom: 12, fontSize: 12 }}>
          模板会影响导出 Word 的段落样式、标题结构和页面观感。如果需要新增模板，请前往“模板中心”上传。
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
              width: 88,
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
          locale={{ emptyText: "暂无模板，请前往“模板中心”上传" }}
        />
      </Modal>
    </div>
  );
}
