import { useRef, useState } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Input,
  Modal,
  Progress,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from "antd";
import {
  CheckCircleOutlined,
  CheckOutlined,
  CloseCircleOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  FileZipOutlined,
  InboxOutlined,
  LoadingOutlined,
  SwapOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import type { RcFile, UploadFile } from "antd/es/upload";
import type { ColumnsType } from "antd/es/table";
import {
  batchDownloadFiles,
  createTranslationJob,
  exportTranslation,
  getJobProgress,
  getTranslationJob,
  type TranslationJob,
  type TranslationSegment,
} from "@/api/translation";

const { Dragger } = Upload;
const { Text } = Typography;
const { TextArea } = Input;

type FileStatus = "pending" | "uploading" | "translating" | "done" | "failed";
type SegmentReview = Record<string, string>;

interface FileEntry {
  uid: string;
  file: File;
  status: FileStatus;
  progress: number;
  jobId?: string;
  job?: TranslationJob;
  errorMessage?: string;
  outputFileId?: string;
  outputFileName?: string;
  reviewing: boolean;
  edits: SegmentReview;
  segments: TranslationSegment[];
  segmentsLoaded: boolean;
}

// ─── Review Modal ─────────────────────────────────────────────────────────────

function ReviewModal({
  entry,
  onEditsChange,
  onExported,
  onClose,
}: {
  entry: FileEntry;
  onEditsChange: (edits: SegmentReview) => void;
  onExported: (fileId: string, fileName: string) => void;
  onClose: () => void;
}) {
  const { message } = App.useApp();
  const [exporting, setExporting] = useState(false);

  const issueSegments = entry.segments.filter((s) => !s.qaPass);
  const resolvedCount = issueSegments.filter((s) => s.id in entry.edits).length;
  const allResolved = issueSegments.length === 0 || resolvedCount === issueSegments.length;

  const acceptSegment = (s: TranslationSegment) =>
    onEditsChange({ ...entry.edits, [s.id]: s.draftTranslation });

  const handleExport = async () => {
    if (!entry.jobId) return;
    setExporting(true);
    try {
      const exportSegs = entry.segments.map((s) => ({
        sourceText: s.sourceText,
        translation: entry.edits[s.id] ?? s.draftTranslation,
      }));
      const result = await exportTranslation(entry.jobId, exportSegs);
      onExported(result.fileId, result.fileName);
      message.success(`审校完成：${result.fileName}`);
      onClose();
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : "导出失败");
    } finally {
      setExporting(false);
    }
  };

  const reviewColumns: ColumnsType<TranslationSegment> = [
    {
      title: "#",
      dataIndex: "order",
      width: 52,
      render: (v: number) => (
        <Text type="secondary" style={{ fontFamily: "monospace", fontSize: 12 }}>
          {String(v + 1).padStart(3, "0")}
        </Text>
      ),
    },
    {
      title: "状态",
      key: "qa",
      width: 100,
      render: (_: unknown, s: TranslationSegment) => {
        if (s.qaPass)
          return <Tag color="success" icon={<CheckCircleOutlined />} style={{ fontSize: 11 }}>通过</Tag>;
        if (s.id in entry.edits)
          return <Tag color="green" icon={<CheckOutlined />} style={{ fontSize: 11 }}>已处理</Tag>;
        return (
          <Tooltip title={s.qaReason || "QA 未通过"}>
            <Tag color="warning" icon={<WarningOutlined />} style={{ fontSize: 11 }}>待处理</Tag>
          </Tooltip>
        );
      },
    },
    {
      title: "原文",
      dataIndex: "sourceText",
      width: "32%",
      render: (v: string) => <Text style={{ fontSize: 13, lineHeight: "1.6" }}>{v}</Text>,
    },
    {
      title: "译文",
      key: "translation",
      render: (_: unknown, s: TranslationSegment) => (
        <TextArea
          value={entry.edits[s.id] ?? s.draftTranslation}
          onChange={(e) => onEditsChange({ ...entry.edits, [s.id]: e.target.value })}
          autoSize={{ minRows: 1, maxRows: 5 }}
          style={{
            fontSize: 13,
            borderColor: s.qaPass ? "#d9d9d9" : s.id in entry.edits ? "#52c41a" : "#faad14",
          }}
        />
      ),
    },
    {
      title: "",
      key: "accept",
      width: 72,
      render: (_: unknown, s: TranslationSegment) => {
        if (s.qaPass || s.id in entry.edits) return null;
        return (
          <Tooltip title="接受此译文，不作修改">
            <Button size="small" icon={<CheckOutlined />} onClick={() => acceptSegment(s)}>
              确认
            </Button>
          </Tooltip>
        );
      },
    },
  ];

  return (
    <Modal
      open={entry.reviewing}
      title={
        <Space>
          <Text strong>{entry.file.name}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            共 {entry.segments.length} 段
            {issueSegments.length > 0 && (
              <> · <Text type="warning" style={{ fontSize: 12 }}>{issueSegments.length} 个 QA 问题</Text></>
            )}
          </Text>
        </Space>
      }
      width="85vw"
      style={{ top: 20 }}
      onCancel={onClose}
      footer={
        <Space>
          {issueSegments.length > 0 && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              已处理 {resolvedCount}/{issueSegments.length} 个 QA 问题
            </Text>
          )}
          <Button onClick={onClose}>关闭</Button>
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            loading={exporting}
            disabled={!allResolved}
            onClick={handleExport}
          >
            完成审校并导出
          </Button>
        </Space>
      }
    >
      {issueSegments.length === 0 && (
        <Alert type="success" message="所有段落均通过 QA 检查，可直接导出" showIcon style={{ marginBottom: 12 }} />
      )}
      {issueSegments.length > 0 && !allResolved && (
        <Alert
          type="warning"
          message={`还有 ${issueSegments.length - resolvedCount} 个 QA 问题待处理。可修改译文，或点击"确认"接受原译文。`}
          showIcon
          style={{ marginBottom: 12 }}
        />
      )}
      <Table
        columns={reviewColumns}
        dataSource={entry.segments}
        rowKey="id"
        size="small"
        pagination={{ pageSize: 30, showSizeChanger: true, pageSizeOptions: ["20", "30", "50"] }}
        sticky
        rowClassName={(s: TranslationSegment) => {
          if (!s.qaPass && !(s.id in entry.edits)) return "qa-fail-row";
          if (!s.qaPass && s.id in entry.edits) return "qa-fixed-row";
          return "";
        }}
        scroll={{ y: "calc(80vh - 260px)" }}
      />
      <style>{`
        .qa-fail-row td { background: #fffbe6 !important; }
        .qa-fixed-row td { background: #f6ffed !important; }
      `}</style>
    </Modal>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Translate() {
  const { message } = App.useApp();
  const [srcLang, setSrcLang] = useState("zh-CN");
  const [tgtLang, setTgtLang] = useState("en-US");
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const pollTimers = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  const swapLangs = () => { setSrcLang(tgtLang); setTgtLang(srcLang); };

  const updateEntry = (uid: string, patch: Partial<FileEntry>) =>
    setEntries((prev) => prev.map((e) => (e.uid === uid ? { ...e, ...patch } : e)));

  const handleBeforeUpload = (f: RcFile) => {
    const ext = f.name.split(".").pop()?.toLowerCase();
    if (!ext || !["docx", "xlsx", "md", "markdown", "pptx"].includes(ext)) {
      message.warning(`${f.name} 不支持，仅限 .docx / .xlsx / .md / .pptx`);
      return Upload.LIST_IGNORE;
    }
    const uid = f.uid;
    setEntries((prev) => [
      ...prev,
      { uid, file: f, status: "pending", progress: 0, reviewing: false, edits: {}, segments: [], segmentsLoaded: false },
    ]);
    setFileList((prev) => [...prev, { uid, name: f.name, status: "done" }]);
    return false;
  };

  const removeEntry = (uid: string) => {
    clearInterval(pollTimers.current[uid]);
    delete pollTimers.current[uid];
    setEntries((prev) => prev.filter((e) => e.uid !== uid));
    setFileList((prev) => prev.filter((item) => item.uid !== uid));
  };

  const startAll = async () => {
    const pending = entries.filter((e) => e.status === "pending");
    if (!pending.length || srcLang === tgtLang) return;
    await Promise.all(
      pending.map(async (entry) => {
        updateEntry(entry.uid, { status: "uploading", progress: 0 });
        try {
          const { id: jobId } = await createTranslationJob(entry.file, srcLang, tgtLang);
          updateEntry(entry.uid, { status: "translating", jobId, progress: 5 });
          const timer = setInterval(async () => {
            try {
              const { status, progress } = await getJobProgress(jobId);
              updateEntry(entry.uid, { progress });
              if (status === "succeeded") {
                clearInterval(timer);
                delete pollTimers.current[entry.uid];
                const { job } = await getTranslationJob(jobId);
                updateEntry(entry.uid, {
                  status: "done", progress: 100, job,
                  outputFileId: job.result?.autoFileId,
                  outputFileName: job.result?.autoFileName,
                });
              } else if (status === "failed") {
                clearInterval(timer);
                delete pollTimers.current[entry.uid];
                // Fetch job detail for error message
                try {
                  const { job: failedJob } = await getTranslationJob(jobId);
                  updateEntry(entry.uid, { status: "failed", progress: 0, errorMessage: failedJob.errorMessage || undefined });
                } catch {
                  updateEntry(entry.uid, { status: "failed", progress: 0 });
                }
              }
            } catch { /* keep polling */ }
          }, 1500);
          pollTimers.current[entry.uid] = timer;
        } catch (err: unknown) {
          updateEntry(entry.uid, { status: "failed", errorMessage: err instanceof Error ? err.message : "提交失败" });
        }
      })
    );
  };

  const openReview = async (uid: string) => {
    const entry = entries.find((e) => e.uid === uid);
    if (!entry?.jobId) return;
    if (!entry.segmentsLoaded) {
      const { segments } = await getTranslationJob(entry.jobId);
      updateEntry(uid, { segments, segmentsLoaded: true, reviewing: true });
    } else {
      updateEntry(uid, { reviewing: true });
    }
  };

  const downloadFile = (entry: FileEntry) => {
    if (!entry.outputFileId) return;
    const a = document.createElement("a");
    a.href = `/api/files/${entry.outputFileId}/download`;
    a.download = entry.outputFileName || entry.file.name;
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  const downloadAll = async () => {
    const ids = entries.filter((e) => e.outputFileId).map((e) => e.outputFileId!);
    if (!ids.length) return;
    try {
      await batchDownloadFiles(ids, "translated_files.zip");
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : "批量下载失败");
    }
  };

  const pendingCount = entries.filter((e) => e.status === "pending").length;
  const doneWithFile = entries.filter((e) => e.outputFileId).length;
  const allSettled = entries.length > 0 && entries.every((e) => e.status === "done" || e.status === "failed");

  const fileColumns: ColumnsType<FileEntry> = [
    {
      title: "文件名",
      key: "name",
      ellipsis: true,
      render: (_: unknown, e: FileEntry) => <Text strong>{e.file.name}</Text>,
    },
    {
      title: "状态",
      key: "status",
      width: 220,
      render: (_: unknown, e: FileEntry) => {
        if (e.status === "pending") return <Tag>待翻译</Tag>;
        if (e.status === "uploading") return <Tag icon={<LoadingOutlined />} color="processing">上传中</Tag>;
        if (e.status === "translating")
          return (
            <Space size={6}>
              <Tag icon={<LoadingOutlined />} color="processing">翻译中</Tag>
              <Progress percent={e.progress} size="small" style={{ width: 80 }} showInfo={false} />
              <Text type="secondary" style={{ fontSize: 11 }}>{e.progress}%</Text>
            </Space>
          );
        if (e.status === "failed") return (
          <Tooltip title={e.errorMessage || "翻译失败，请重试"}>
            <Tag icon={<CloseCircleOutlined />} color="error" style={{ cursor: "help" }}>失败</Tag>
          </Tooltip>
        );
        if (e.outputFileId) return <Tag icon={<CheckCircleOutlined />} color="success">完成</Tag>;
        return <Tag color="blue">需审校</Tag>;
      },
    },
    {
      title: "操作",
      key: "action",
      width: 200,
      render: (_: unknown, e: FileEntry) => {
        // Pending: show remove button
        if (e.status === "pending") {
          return (
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={() => removeEntry(e.uid)}
            >
              移除
            </Button>
          );
        }
        if (e.status !== "done") return null;
        return (
          <Space size={8}>
            <Button size="small" icon={<EditOutlined />} onClick={() => void openReview(e.uid)}>
              {e.outputFileId ? "重新审校" : "审校"}
            </Button>
            {e.outputFileId && (
              <Button type="primary" size="small" icon={<DownloadOutlined />} onClick={() => downloadFile(e)}>
                下载
              </Button>
            )}
          </Space>
        );
      },
    },
  ];

  return (
    // height:100% fills the scrollable content wrapper in AppLayout
    <div style={{ maxWidth: 1100, margin: "0 auto", height: "100%", display: "flex", flexDirection: "column", gap: 16 }}>

      {/* Top row: upload area + language card */}
      <div style={{ display: "flex", gap: 20, alignItems: "flex-start", flexShrink: 0 }}>
        {/* Upload dragger — no internal file list */}
        <div style={{ flex: 1 }}>
          <Card>
            <Dragger
              accept=".docx,.xlsx,.md,.markdown,.pptx"
              multiple
              fileList={[]}
              beforeUpload={handleBeforeUpload}
              openFileDialogOnClick
            >
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p className="ant-upload-text">点击或拖入待翻译的文件（支持多选）</p>
              <p className="ant-upload-hint">支持 .docx / .xlsx / .md / .pptx，可同时上传多个文件</p>
            </Dragger>
          </Card>
        </div>

        {/* Language selector card — same width as Convert's right card */}
        <Card title="翻译方向" style={{ width: 260, flexShrink: 0 }}>
          <Space direction="vertical" style={{ width: "100%" }} size="middle">
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>源语言</Text>
              <Select value={srcLang} onChange={setSrcLang} style={{ width: "100%", marginTop: 4 }}>
                <Select.Option value="zh-CN">简体中文</Select.Option>
                <Select.Option value="en-US">English</Select.Option>
              </Select>
            </div>
            <div style={{ textAlign: "center" }}>
              <Button shape="circle" icon={<SwapOutlined rotate={90} />} onClick={swapLangs} />
            </div>
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>目标语言</Text>
              <Select value={tgtLang} onChange={setTgtLang} style={{ width: "100%", marginTop: 4 }}>
                <Select.Option value="en-US">English</Select.Option>
                <Select.Option value="zh-CN">简体中文</Select.Option>
              </Select>
            </div>
          </Space>
          <Button
            type="primary"
            block
            size="large"
            disabled={pendingCount === 0 || srcLang === tgtLang}
            onClick={() => void startAll()}
            style={{ marginTop: 20 }}
          >
            开始翻译{pendingCount > 0 ? `（${pendingCount} 个文件）` : ""}
          </Button>
        </Card>
      </div>

      {/* File list — fills remaining height, Card body scrolls */}
      <Card
        size="small"
        style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}
        styles={{ body: { flex: 1, overflow: "auto", padding: "0 0 4px", minHeight: 0 } }}
        title={entries.length > 0 ? `文件列表（${entries.length} 个）` : "文件列表"}
        extra={
          doneWithFile > 1 && allSettled ? (
            <Button icon={<FileZipOutlined />} size="small" onClick={() => void downloadAll()}>
              打包下载全部（{doneWithFile} 个）
            </Button>
          ) : null
        }
      >
        <Table
          columns={fileColumns}
          dataSource={entries}
          rowKey="uid"
          size="small"
          pagination={false}
          locale={{ emptyText: "拖入或点击上方区域添加文件" }}
        />
      </Card>

      {/* Review modals */}
      {entries
        .filter((e) => e.reviewing && e.segmentsLoaded)
        .map((e) => (
          <ReviewModal
            key={e.uid}
            entry={e}
            onEditsChange={(edits) => updateEntry(e.uid, { edits })}
            onExported={(fileId, fileName) => updateEntry(e.uid, { outputFileId: fileId, outputFileName: fileName })}
            onClose={() => updateEntry(e.uid, { reviewing: false })}
          />
        ))}
    </div>
  );
}
