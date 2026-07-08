import { useState } from "react";
import { App, Button, Card, Progress, Select, Space, Table, Tag, Tooltip, Typography, Upload } from "antd";
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  FileZipOutlined,
  InboxOutlined,
  LoadingOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import TranslationReviewModal from "@/components/translation/TranslationReviewModal";
import type { FileEntry } from "@/hooks/useTranslationQueue";
import { useTranslationQueue } from "@/hooks/useTranslationQueue";

const { Dragger } = Upload;
const { Text } = Typography;

export default function Translate() {
  const { message } = App.useApp();
  const [sourceLang, setSourceLang] = useState("zh-CN");
  const [targetLang, setTargetLang] = useState("en-US");
  const {
    entries,
    startAll,
    removeEntry,
    handleBeforeUpload,
    loadReviewSegments,
    downloadFile,
    downloadAll,
    updateEntry,
    exportReviewedTranslation,
  } = useTranslationQueue({
    message,
    sourceLang,
    targetLang,
  });

  const swapLanguages = () => {
    setSourceLang(targetLang);
    setTargetLang(sourceLang);
  };

  const pendingCount = entries.filter((entry) => entry.status === "pending").length;
  const completedDownloads = entries.filter((entry) => entry.outputFileId).length;
  const allSettled =
    entries.length > 0 && entries.every((entry) => entry.status === "done" || entry.status === "failed");

  const fileColumns: ColumnsType<FileEntry> = [
    {
      title: "文件",
      key: "name",
      ellipsis: true,
      render: (_: unknown, entry) => <Text strong>{entry.file.name}</Text>,
    },
    {
      title: "状态",
      key: "status",
      width: 220,
      render: (_: unknown, entry) => {
        if (entry.status === "pending") {
          return <Tag>待开始</Tag>;
        }
        if (entry.status === "uploading") {
          return (
            <Tag icon={<LoadingOutlined />} color="processing">
              上传中
            </Tag>
          );
        }
        if (entry.status === "translating") {
          return (
            <Space size={6}>
              <Tag icon={<LoadingOutlined />} color="processing">
                翻译中
              </Tag>
              <Progress percent={entry.progress} size="small" style={{ width: 80 }} showInfo={false} />
              <Text type="secondary" style={{ fontSize: 11 }}>
                {entry.progress}%
              </Text>
            </Space>
          );
        }
        if (entry.status === "failed") {
          return (
            <Tooltip title={entry.errorMessage || "翻译失败，请稍后重试。"}>
              <Tag icon={<CloseCircleOutlined />} color="error" style={{ cursor: "help" }}>
                失败
              </Tag>
            </Tooltip>
          );
        }
        if (entry.outputFileId) {
          return (
            <Tag icon={<CheckCircleOutlined />} color="success">
              已完成
            </Tag>
          );
        }
        return <Tag color="blue">待复核</Tag>;
      },
    },
    {
      title: "操作",
      key: "action",
      width: 220,
      render: (_: unknown, entry) => {
        if (entry.status === "pending") {
          return (
            <Button size="small" danger icon={<DeleteOutlined />} onClick={() => removeEntry(entry.uid)}>
              移除
            </Button>
          );
        }
        if (entry.status !== "done") {
          return null;
        }

        const needsReview = !entry.job?.result?.allQaPass;
        const canDownload = Boolean(entry.outputFileId);

        return (
          <Space size={8}>
            {needsReview ? (
              <Button size="small" icon={<EditOutlined />} onClick={() => void loadReviewSegments(entry.uid)}>
                {entry.outputFileId ? "再次复核" : "复核"}
              </Button>
            ) : null}
            {canDownload ? (
              <Button type="primary" size="small" icon={<DownloadOutlined />} onClick={() => downloadFile(entry)}>
                下载
              </Button>
            ) : null}
          </Space>
        );
      },
    },
  ];

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", height: "100%", display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", gap: 20, alignItems: "flex-start", flexShrink: 0 }}>
        <div style={{ flex: 1 }}>
          <Card>
            <Dragger
              accept=".docx,.xlsx,.md,.markdown"
              multiple
              fileList={[]}
              beforeUpload={handleBeforeUpload}
              openFileDialogOnClick
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">点击或拖拽文件到这里，加入翻译队列。</p>
              <p className="ant-upload-hint">支持格式：.docx、.xlsx、.md</p>
            </Dragger>
          </Card>
        </div>

        <Card title="翻译方向" style={{ width: 280, flexShrink: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
            <Select value={sourceLang} onChange={setSourceLang} style={{ flex: 1 }} size="middle">
              <Select.Option value="zh-CN">简体中文</Select.Option>
              <Select.Option value="en-US">英文</Select.Option>
            </Select>
            <Button
              type="text"
              shape="circle"
              icon={<SwapOutlined />}
              onClick={swapLanguages}
              style={{ flexShrink: 0, color: "#1b3a6b" }}
            />
            <Select value={targetLang} onChange={setTargetLang} style={{ flex: 1 }} size="middle">
              <Select.Option value="en-US">英文</Select.Option>
              <Select.Option value="zh-CN">简体中文</Select.Option>
            </Select>
          </div>

          <Button
            type="primary"
            block
            size="large"
            disabled={pendingCount === 0 || sourceLang === targetLang}
            onClick={() => void startAll()}
          >
            {pendingCount > 0 ? `开始翻译（${pendingCount}）` : "开始翻译"}
          </Button>
        </Card>
      </div>

      {entries.length > 0 ? (
        <Card
          size="small"
          style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}
          styles={{ body: { flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", padding: 0 } }}
          title={`文件列表（${entries.length}）`}
          extra={
            completedDownloads > 1 && allSettled ? (
              <Button icon={<FileZipOutlined />} size="small" onClick={() => void downloadAll()}>
                全部下载（${completedDownloads}）
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
            sticky
            scroll={{ y: "calc(100vh - 420px)" }}
            style={{ flex: 1 }}
          />
        </Card>
      ) : null}

      {entries
        .filter((entry) => entry.reviewing && entry.segmentsLoaded)
        .map((entry) => (
          <TranslationReviewModal
            key={entry.uid}
            entry={entry}
            onEditsChange={(edits) => updateEntry(entry.uid, { edits })}
            onConfirmedChange={(confirmed) => updateEntry(entry.uid, { confirmed })}
            onExported={(fileId, fileName) => updateEntry(entry.uid, { outputFileId: fileId, outputFileName: fileName })}
            onExportStale={() => updateEntry(entry.uid, { outputFileId: undefined, outputFileName: undefined })}
            onClose={() => updateEntry(entry.uid, { reviewing: false })}
            onExport={exportReviewedTranslation}
          />
        ))}
    </div>
  );
}
