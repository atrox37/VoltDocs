import { useState } from "react";
import { Alert, App, Button, Input, Modal, Space, Table, Tag, Typography } from "antd";
import { CheckCircleOutlined, CheckOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type { TranslationSegment } from "@/api/translation";
import type { ConfirmedReview, FileEntry, SegmentReview } from "@/hooks/useTranslationQueue";

const { Text } = Typography;
const { TextArea } = Input;

interface TranslationReviewModalProps {
  entry: FileEntry;
  onEditsChange: (edits: SegmentReview) => void;
  onConfirmedChange: (confirmed: ConfirmedReview) => void;
  onExported: (fileId: string, fileName: string) => void;
  onExportStale: () => void;
  onClose: () => void;
  onExport: (entry: FileEntry) => Promise<{ fileId: string; fileName: string } | null>;
}

export default function TranslationReviewModal({
  entry,
  onEditsChange,
  onConfirmedChange,
  onExported,
  onExportStale,
  onClose,
  onExport,
}: TranslationReviewModalProps) {
  const { message } = App.useApp();
  const [exporting, setExporting] = useState(false);

  const issueSegments = entry.segments.filter((segment) => !segment.qaPass);
  const visibleSegments = issueSegments.length > 0 ? issueSegments : [];
  const confirmedCount = issueSegments.filter((segment) => entry.confirmed[segment.id]).length;
  const allConfirmed = issueSegments.length === 0 || confirmedCount === issueSegments.length;
  const readOnlyInspect = issueSegments.length === 0;

  const currentTranslation = (segment: TranslationSegment) => entry.edits[segment.id] ?? segment.draftTranslation;

  const confirmSegment = (segment: TranslationSegment) => {
    onEditsChange({ ...entry.edits, [segment.id]: currentTranslation(segment) });
    onConfirmedChange({ ...entry.confirmed, [segment.id]: true });
  };

  const confirmAll = () => {
    const edits = { ...entry.edits };
    const confirmed = { ...entry.confirmed };
    for (const segment of issueSegments) {
      edits[segment.id] = currentTranslation(segment);
      confirmed[segment.id] = true;
    }
    onEditsChange(edits);
    onConfirmedChange(confirmed);
  };

  const handleExport = async (): Promise<boolean> => {
    if (!allConfirmed || exporting) {
      return false;
    }
    setExporting(true);
    try {
      const result = await onExport(entry);
      if (!result) {
        return false;
      }
      onExported(result.fileId, result.fileName);
      message.success("译文已保存，可在文件列表中下载。");
      return true;
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : "导出失败。");
      return false;
    } finally {
      setExporting(false);
    }
  };

  const handleConfirm = async () => {
    if (!allConfirmed) {
      return;
    }
    if (issueSegments.length === 0) {
      onClose();
      return;
    }
    const ok = await handleExport();
    if (ok) {
      onClose();
    }
  };

  const handleDismiss = () => {
    if (allConfirmed && issueSegments.length > 0) {
      void handleConfirm();
      return;
    }
    onClose();
  };

  const columns: ColumnsType<TranslationSegment> = [
    {
      title: "#",
      dataIndex: "order",
      width: 52,
      render: (value: number) => (
        <Text type="secondary" style={{ fontFamily: "monospace", fontSize: 12 }}>
          {String(value + 1).padStart(3, "0")}
        </Text>
      ),
    },
    {
      title: "QA 问题",
      key: "qa",
      width: 220,
      render: (_: unknown, segment) => {
        if (entry.confirmed[segment.id]) {
          return (
            <Tag color="green" icon={<CheckOutlined />} style={{ fontSize: 11 }}>
              已确认
            </Tag>
          );
        }
        return (
          <Text type="warning" style={{ fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {segment.qaReason || "QA 检查未通过"}
          </Text>
        );
      },
    },
    {
      title: "原文",
      dataIndex: "sourceText",
      render: (value: string) => (
        <Text style={{ fontSize: 13, lineHeight: "1.6", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {value}
        </Text>
      ),
    },
    {
      title: "译文",
      key: "translation",
      render: (_: unknown, segment) => (
        <TextArea
          value={currentTranslation(segment)}
          readOnly={readOnlyInspect}
          onChange={(event) => {
            onEditsChange({ ...entry.edits, [segment.id]: event.target.value });
            onExportStale();
            if (entry.confirmed[segment.id]) {
              onConfirmedChange({ ...entry.confirmed, [segment.id]: false });
            }
          }}
          autoSize={{ minRows: 1, maxRows: 8 }}
          style={{
            fontSize: 13,
            borderColor: readOnlyInspect ? "#d9d9d9" : entry.confirmed[segment.id] ? "#52c41a" : "#faad14",
          }}
        />
      ),
    },
    {
      title: "操作",
      key: "accept",
      width: 88,
      align: "center",
      render: (_: unknown, segment) => (
        <Button
          size="small"
          type={entry.confirmed[segment.id] ? "default" : "primary"}
          icon={<CheckOutlined />}
          disabled={readOnlyInspect}
          onClick={() => confirmSegment(segment)}
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
            {issueSegments.length > 0
              ? `${issueSegments.length} 个 QA 问题待复核，已确认 ${confirmedCount}/${issueSegments.length}`
              : "当前文件没有待处理的 QA 问题"}
          </Text>
          {allConfirmed && issueSegments.length > 0 ? (
            <Tag color="success" icon={<CheckCircleOutlined />} style={{ fontSize: 11 }}>
              可保存
            </Tag>
          ) : null}
        </Space>
      }
      width="min(1100px, 92vw)"
      style={{ top: 20 }}
      onCancel={handleDismiss}
      footer={
        issueSegments.length > 0 ? (
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {allConfirmed ? "所有问题都已确认，可以保存复核结果。" : `还有 ${issueSegments.length - confirmedCount} 项待确认。`}
            </Text>
            <Button
              type="primary"
              loading={exporting}
              disabled={!allConfirmed}
              icon={<CheckOutlined />}
              onClick={() => void handleConfirm()}
            >
              保存复核
            </Button>
          </Space>
        ) : null
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message={
          issueSegments.length > 0
            ? "请逐条复核被 QA 标记的译文，确认后再保存。"
            : "当前文件没有需要人工处理的 QA 问题。"
        }
      />
      {issueSegments.length > 0 ? (
        <div style={{ marginBottom: 12 }}>
          <Button icon={<CheckOutlined />} onClick={confirmAll}>
            全部确认
          </Button>
        </div>
      ) : null}
      <Table
        className="review-modal-table"
        columns={columns}
        dataSource={visibleSegments}
        rowKey="id"
        size="small"
        pagination={{ pageSize: 30, showSizeChanger: true, pageSizeOptions: ["20", "30", "50"] }}
        rowClassName={(segment) => (entry.confirmed[segment.id] ? "qa-fixed-row" : "qa-fail-row")}
        scroll={{ y: "calc(80vh - 240px)" }}
        locale={{ emptyText: "No QA issues" }}
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
