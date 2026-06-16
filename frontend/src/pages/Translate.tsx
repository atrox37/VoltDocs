import React, { useRef, useState } from "react";
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
type ConfirmedReview = Record<string, boolean>;

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
  confirmed: ConfirmedReview;
  segments: TranslationSegment[];
  segmentsLoaded: boolean;
}

// ─── Review Modal ─────────────────────────────────────────────────────────────

function ReviewModal({
  entry,
  onEditsChange,
  onConfirmedChange,
  onExported,
  onExportStale,
  onClose,
}: {
  entry: FileEntry;
  onEditsChange: (edits: SegmentReview) => void;
  onConfirmedChange: (confirmed: ConfirmedReview) => void;
  onExported: (fileId: string, fileName: string) => void;
  onExportStale: () => void;
  onClose: () => void;
}) {
  const { message } = App.useApp();
  const [exporting, setExporting] = useState(false);

  const issueSegments = entry.segments.filter((s) => !s.qaPass);
  const confirmedCount = issueSegments.filter((s) => entry.confirmed[s.id]).length;
  const allConfirmed = issueSegments.length === 0 || confirmedCount === issueSegments.length;

  const currentTranslation = (s: TranslationSegment) =>
    entry.edits[s.id] ?? s.draftTranslation;

  const confirmSegment = (s: TranslationSegment) => {
    const translation = currentTranslation(s);
    onEditsChange({ ...entry.edits, [s.id]: translation });
    onConfirmedChange({ ...entry.confirmed, [s.id]: true });
  };

  const confirmAll = () => {
    const newEdits = { ...entry.edits };
    const newConfirmed = { ...entry.confirmed };
    for (const s of issueSegments) {
      newEdits[s.id] = currentTranslation(s);
      newConfirmed[s.id] = true;
    }
    onEditsChange(newEdits);
    onConfirmedChange(newConfirmed);
  };

  const doExport = async (): Promise<boolean> => {
    if (!entry.jobId || exporting || !allConfirmed) return false;
    setExporting(true);
    try {
      const exportSegs = entry.segments.map((s) => ({
        sourceText: s.sourceText,
        translation: entry.edits[s.id] ?? s.draftTranslation,
      }));
      const result = await exportTranslation(entry.jobId, exportSegs);
      onExported(result.fileId, result.fileName);
      message.success("译文已保存，可在文件列表下载");
      return true;
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : "导出失败");
      return false;
    } finally {
      setExporting(false);
    }
  };

  const handleConfirm = async () => {
    if (!allConfirmed) return;
    if (issueSegments.length === 0) {
      onClose();
      return;
    }
    const ok = await doExport();
    if (ok) onClose();
  };

  const handleDismiss = () => {
    if (allConfirmed && issueSegments.length > 0) {
      void handleConfirm();
      return;
    }
    onClose();
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
      title: "QA 问题",
      key: "qa",
      width: 200,
      render: (_: unknown, s: TranslationSegment) => {
        if (entry.confirmed[s.id])
          return <Tag color="green" icon={<CheckOutlined />} style={{ fontSize: 11 }}>已确认</Tag>;
        return (
          <Text type="warning" style={{ fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {s.qaReason || "QA 未通过"}
          </Text>
        );
      },
    },
    {
      title: "原文",
      dataIndex: "sourceText",
      render: (v: string) => (
        <Text style={{ fontSize: 13, lineHeight: "1.6", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{v}</Text>
      ),
    },
    {
      title: "译文（可直接修改）",
      key: "translation",
      render: (_: unknown, s: TranslationSegment) => (
        <TextArea
          value={currentTranslation(s)}
          onChange={(e) => {
            onEditsChange({ ...entry.edits, [s.id]: e.target.value });
            onExportStale();
            if (entry.confirmed[s.id]) {
              onConfirmedChange({ ...entry.confirmed, [s.id]: false });
            }
          }}
          autoSize={{ minRows: 1, maxRows: 8 }}
          style={{
            fontSize: 13,
            borderColor: entry.confirmed[s.id] ? "#52c41a" : "#faad14",
          }}
        />
      ),
    },
    {
      title: "操作",
      key: "accept",
      width: 88,
      align: "center",
      render: (_: unknown, s: TranslationSegment) => (
        <Button
          size="small"
          type={entry.confirmed[s.id] ? "default" : "primary"}
          icon={<CheckOutlined />}
          onClick={() => confirmSegment(s)}
        >
          确认
        </Button>
      ),
    },
  ];

  return (
    <Modal
      open={entry.reviewing}
      title={
        <Space>
          <Text strong>{entry.file.name}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {issueSegments.length} 个 QA 问题 · 已确认 {confirmedCount}/{issueSegments.length}
          </Text>
          {allConfirmed && issueSegments.length > 0 && (
            <Tag color="success" icon={<CheckCircleOutlined />} style={{ fontSize: 11 }}>可确定</Tag>
          )}
        </Space>
      }
      width="min(1100px, 92vw)"
      style={{ top: 20 }}
      onCancel={handleDismiss}
      footer={
        <Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {allConfirmed
              ? "全部问题已确认，点击确定保存译文"
              : `还有 ${issueSegments.length - confirmedCount} 项未确认`}
          </Text>
          <Button
            type="primary"
            loading={exporting}
            disabled={!allConfirmed}
            icon={<CheckOutlined />}
            onClick={() => void handleConfirm()}
          >
            确定
          </Button>
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="请逐条修改译文并点击「确认」，或点击「全部确认」。全部确认后点击「确定」保存；下载请在文件列表操作。可重新审校并再次确认以更新译文。"
      />
      {issueSegments.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <Button icon={<CheckOutlined />} onClick={confirmAll}>
            全部确认
          </Button>
        </div>
      )}
      <Table
        className="review-modal-table"
        columns={reviewColumns}
        dataSource={issueSegments}
        rowKey="id"
        size="small"
        pagination={{ pageSize: 30, showSizeChanger: true, pageSizeOptions: ["20", "30", "50"] }}
        rowClassName={(s: TranslationSegment) =>
          entry.confirmed[s.id] ? "qa-fixed-row" : "qa-fail-row"
        }
        scroll={{ y: "calc(80vh - 320px)" }}
        locale={{ emptyText: "无 QA 问题" }}
      />
      <style>{`
        .qa-fail-row td { background: #fffbe6 !important; }
        .qa-fixed-row td { background: #f6ffed !important; }
        .ant-table-wrapper { overflow-x: hidden; }
        .review-modal-table .ant-table-cell { white-space: normal !important; word-break: break-word; vertical-align: top; }
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
    if (!ext || !["docx", "xlsx", "md", "markdown"].includes(ext)) {
      message.warning(`${f.name} 不支持，仅限 .docx / .xlsx / .md`);
      return Upload.LIST_IGNORE;
    }
    const uid = f.uid;
    setEntries((prev) => [
      ...prev,
      { uid, file: f, status: "pending", progress: 0, reviewing: false, edits: {}, confirmed: {}, segments: [], segmentsLoaded: false },
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
        if (e.status === "failed")
          return (
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
        if (e.status === "pending") {
          return (
            <Button size="small" danger icon={<DeleteOutlined />} onClick={() => removeEntry(e.uid)}>
              移除
            </Button>
          );
        }
        if (e.status !== "done") return null;
        const qaAllPass = e.job?.result?.allQaPass;
        const needsReview = !qaAllPass;
        const canDownload = Boolean(e.outputFileId);
        return (
          <Space size={8}>
            {needsReview && (
              <Button size="small" icon={<EditOutlined />} onClick={() => void openReview(e.uid)}>
                {e.outputFileId ? "重新审校" : "审校"}
              </Button>
            )}
            {canDownload && (
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
    <div style={{ maxWidth: 1100, margin: "0 auto", height: "100%", display: "flex", flexDirection: "column", gap: 16 }}>

      {/* Top row: upload area + language card */}
      <div style={{ display: "flex", gap: 20, alignItems: "flex-start", flexShrink: 0 }}>
        {/* Upload dragger */}
        <div style={{ flex: 1 }}>
          <Card>
            <Dragger
              accept=".docx,.xlsx,.md,.markdown"
              multiple
              fileList={[]}
              beforeUpload={handleBeforeUpload}
              openFileDialogOnClick
            >
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p className="ant-upload-text">点击或拖入待翻译的文件（支持多选）</p>
              <p className="ant-upload-hint">支持 .docx / .xlsx / .md，可同时上传多个文件</p>
            </Dragger>
          </Card>
        </div>

        {/* Language card — compact inline layout */}
        <Card title="翻译方向" style={{ width: 280, flexShrink: 0 }}>
          {/* Source → Target on one row */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
            <Select
              value={srcLang}
              onChange={setSrcLang}
              style={{ flex: 1 }}
              size="middle"
            >
              <Select.Option value="zh-CN">简体中文</Select.Option>
              <Select.Option value="en-US">English</Select.Option>
            </Select>
            <Button
              type="text"
              shape="circle"
              icon={<SwapOutlined />}
              onClick={swapLangs}
              style={{ flexShrink: 0, color: "#1b3a6b" }}
            />
            <Select
              value={tgtLang}
              onChange={setTgtLang}
              style={{ flex: 1 }}
              size="middle"
            >
              <Select.Option value="en-US">English</Select.Option>
              <Select.Option value="zh-CN">简体中文</Select.Option>
            </Select>
          </div>

          <Button
            type="primary"
            block
            size="large"
            disabled={pendingCount === 0 || srcLang === tgtLang}
            onClick={() => void startAll()}
          >
            开始翻译{pendingCount > 0 ? `（${pendingCount} 个文件）` : ""}
          </Button>
        </Card>
      </div>

      {/* File list — only shown when there are entries; sticky header, body scrolls */}
      {entries.length > 0 && (
        <Card
          size="small"
          style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}
          styles={{ body: { flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", padding: 0 } }}
          title={`文件列表（${entries.length} 个）`}
          extra={
            doneWithFile > 1 && allSettled ? (
              <Button icon={<FileZipOutlined />} size="small" onClick={() => void downloadAll()}>
                打包下载全部（{doneWithFile} 个）
              </Button>
            ) : null
          }
        >
          {/* sticky prop keeps the header fixed while tbody scrolls */}
          <Table
            columns={fileColumns}
            dataSource={entries}
            rowKey="uid"
            size="small"
            pagination={false}
            sticky
            scroll={{ y: "calc(100vh - 420px)" }}
            style={{ flex: 1 }}
          />
        </Card>
      )}

      {/* Review modals */}
      {entries
        .filter((e) => e.reviewing && e.segmentsLoaded)
        .map((e) => (
          <ReviewModal
            key={e.uid}
            entry={e}
            onEditsChange={(edits) => updateEntry(e.uid, { edits })}
            onConfirmedChange={(confirmed) => updateEntry(e.uid, { confirmed })}
            onExported={(fileId, fileName) => updateEntry(e.uid, { outputFileId: fileId, outputFileName: fileName })}
            onExportStale={() => updateEntry(e.uid, { outputFileId: undefined, outputFileName: undefined })}
            onClose={() => updateEntry(e.uid, { reviewing: false })}
          />
        ))}
    </div>
  );
}
