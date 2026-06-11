import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Alert, App, Button, Card, Input, Progress, Space, Spin, Table, Tag, Typography } from "antd";
import { ArrowLeftOutlined, CheckCircleOutlined, DownloadOutlined, EditOutlined } from "@ant-design/icons";
import {
  exportTranslation,
  getTranslationJob,
  listTranslationJobs,
  type TranslationJob,
  type TranslationSegment,
} from "@/api/translation";

const { Text } = Typography;
const { TextArea } = Input;

function JobList({
  jobs,
  loading,
  onOpen,
}: {
  jobs: TranslationJob[];
  loading: boolean;
  onOpen: (id: string) => void;
}) {
  const { message } = App.useApp();

  const handleDirectDownload = (job: TranslationJob) => {
    const fileId = job.result?.autoFileId;
    if (!fileId) return;
    const a = document.createElement("a");
    a.href = `/api/files/${fileId}/download`;
    a.download = job.result?.autoFileName || "translated";
    document.body.appendChild(a);
    a.click();
    a.remove();
    message.success("已开始下载译文");
  };

  const columns = [
    {
      title: "文件名",
      key: "name",
      render: (_: unknown, job: TranslationJob) => job.payload?.fileName || job.id.slice(0, 8),
    },
    {
      title: "翻译方向",
      key: "lang",
      render: (_: unknown, job: TranslationJob) => `${job.payload?.sourceLang || "?"} -> ${job.payload?.targetLang || "?"}`,
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      render: (status: string, job: TranslationJob) => {
        if (status === "succeeded") {
          if (job.result?.allQaPass) {
            return (
              <Tag color="success" icon={<CheckCircleOutlined />}>
                完成 · QA 全部通过
              </Tag>
            );
          }
          return <Tag color="blue">完成 · 需审校</Tag>;
        }
        const color = status === "failed" ? "error" : "processing";
        const label = status === "failed" ? "失败" : status === "running" ? "翻译中" : "排队中";
        return <Tag color={color}>{label}</Tag>;
      },
    },
    {
      title: "进度",
      dataIndex: "progress",
      key: "progress",
      width: 140,
      render: (value: number) => <Progress percent={value} size="small" />,
    },
    {
      title: "创建时间",
      dataIndex: "createdAt",
      key: "createdAt",
      render: (value: string) => new Date(value).toLocaleString("zh-CN"),
    },
    {
      title: "操作",
      key: "action",
      render: (_: unknown, job: TranslationJob) => {
        if (job.status !== "succeeded") return null;
        if (job.result?.allQaPass) {
          return (
            <Button type="primary" size="small" icon={<DownloadOutlined />} onClick={() => handleDirectDownload(job)}>
              直接下载
            </Button>
          );
        }
        return (
          <Button type="link" icon={<EditOutlined />} onClick={() => onOpen(job.id)}>
            进入审校
          </Button>
        );
      },
    },
  ];

  return (
    <Card>
      <Table
        loading={loading}
        columns={columns}
        dataSource={jobs}
        rowKey="id"
        pagination={{ pageSize: 10 }}
        size="middle"
        locale={{ emptyText: "暂无翻译任务，请先前往“文档翻译”上传文件" }}
      />
    </Card>
  );
}

function ReviewEditor({
  job,
  segments,
  onBack,
}: {
  job: TranslationJob;
  segments: TranslationSegment[];
  onBack: () => void;
}) {
  const { message } = App.useApp();
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [exporting, setExporting] = useState(false);

  const issueSegments = segments.filter((segment) => !segment.qaPass);
  const confirmedCount = Object.keys(edits).length;
  const progress = issueSegments.length > 0 ? Math.round((confirmedCount / issueSegments.length) * 100) : 100;

  const handleExport = async () => {
    setExporting(true);
    try {
      const exportSegments = segments.map((segment) => ({
        sourceText: segment.sourceText,
        translation: edits[segment.id] ?? segment.draftTranslation,
      }));
      const result = await exportTranslation(job.id, exportSegments);
      const a = document.createElement("a");
      a.href = result.downloadUrl;
      a.download = result.fileName;
      document.body.appendChild(a);
      a.click();
      a.remove();
      message.success(`导出成功：${result.fileName}`);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : "导出失败");
    } finally {
      setExporting(false);
    }
  };

  const columns = [
    {
      title: "#",
      dataIndex: "order",
      key: "order",
      width: 56,
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
      render: (_: unknown, segment: TranslationSegment) => (
        <Text type="warning" style={{ fontSize: 12 }}>
          {edits[segment.id] !== undefined ? "已修正" : segment.qaReason || "QA 未通过"}
        </Text>
      ),
    },
    {
      title: "原文",
      dataIndex: "sourceText",
      key: "sourceText",
      width: "35%",
      render: (value: string) => <Text style={{ fontSize: 13, lineHeight: "1.6" }}>{value}</Text>,
    },
    {
      title: "译文",
      key: "translation",
      render: (_: unknown, segment: TranslationSegment) => (
        <TextArea
          value={edits[segment.id] ?? segment.draftTranslation}
          onChange={(event) => setEdits((prev) => ({ ...prev, [segment.id]: event.target.value }))}
          autoSize={{ minRows: 1, maxRows: 5 }}
          style={{
            fontSize: 13,
            borderColor: edits[segment.id] === undefined ? "#faad14" : "#52c41a",
          }}
        />
      ),
    },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ marginBottom: 16, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <Button icon={<ArrowLeftOutlined />} onClick={onBack}>
          返回
        </Button>
        <Text strong>{job.payload?.fileName}</Text>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {job.payload?.sourceLang} → {job.payload?.targetLang} · 共 {segments.length} 段
        </Text>
        <div style={{ flex: 1 }} />
        {issueSegments.length > 0 && (
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>
              待修正 {issueSegments.length} 段
            </Text>
            <div style={{ width: 140 }}>
              <Progress percent={progress} size="small" format={() => `${confirmedCount}/${issueSegments.length}`} />
            </div>
          </Space>
        )}
        <Button type="primary" icon={<DownloadOutlined />} loading={exporting} onClick={handleExport}>
          导出译文
        </Button>
      </div>

      {issueSegments.length === 0 && (
        <Alert
          type="success"
          message="所有段落均通过 QA 检查"
          description="可直接点击“导出译文”下载翻译结果。"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      <Card style={{ flex: 1, overflow: "hidden" }} styles={{ body: { padding: 0, height: "100%", overflow: "auto" } }}>
        <Table
          columns={columns}
          dataSource={issueSegments}
          rowKey="id"
          pagination={{ pageSize: 30, showSizeChanger: true }}
          size="small"
          sticky
          rowClassName={(segment: TranslationSegment) => (edits[segment.id] !== undefined ? "qa-fixed-row" : "qa-fail-row")}
          locale={{ emptyText: "所有 QA 检查均已通过" }}
        />
      </Card>

      <style>{`
        .qa-fail-row td { background: #fffbe6 !important; }
        .qa-fixed-row td { background: #f6ffed !important; }
      `}</style>
    </div>
  );
}

export default function Reviews() {
  const { message } = App.useApp();
  const [searchParams] = useSearchParams();
  const preSelectedJobId = searchParams.get("jobId");

  const [jobs, setJobs] = useState<TranslationJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeJobId, setActiveJobId] = useState<string | null>(preSelectedJobId);
  const [segments, setSegments] = useState<TranslationSegment[]>([]);
  const [loadingJob, setLoadingJob] = useState(false);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const { jobs: data } = await listTranslationJobs();
        setJobs(data);
        if (preSelectedJobId) {
          void openJob(preSelectedJobId);
        }
      } finally {
        setLoading(false);
      }
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const openJob = async (jobId: string) => {
    setLoadingJob(true);
    try {
      const { segments: data } = await getTranslationJob(jobId);
      setSegments(data);
      setActiveJobId(jobId);
    } catch (err: unknown) {
      setActiveJobId(null);
      setSegments([]);
      message.error(err instanceof Error ? err.message : "无法打开该审校记录");
    } finally {
      setLoadingJob(false);
    }
  };

  const activeJob = jobs.find((job) => job.id === activeJobId);

  if (loadingJob) {
    return (
      <div style={{ textAlign: "center", padding: 80 }}>
        <Spin size="large" tip="加载审校数据..." />
      </div>
    );
  }

  if (activeJobId && activeJob) {
    return (
      <ReviewEditor
        job={activeJob}
        segments={segments}
        onBack={() => {
          setActiveJobId(null);
          setSegments([]);
        }}
      />
    );
  }

  return <JobList jobs={jobs} loading={loading} onOpen={openJob} />;
}
