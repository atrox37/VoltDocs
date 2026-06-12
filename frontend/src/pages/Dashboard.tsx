import { useEffect, useState } from "react";
import { Card, Col, Row, Statistic, Table, Tag, Typography, Spin } from "antd";
import {
  CheckCircleOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  TranslationOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { get } from "@/api/client";

const { Text } = Typography;

// ── Types ──────────────────────────────────────────────────────────────────

interface TopTerm {
  sourceTerm: string;
  targetTerm: string;
  sourceLang: string;
  targetLang: string;
  hitCount: number;
}

interface LangPair {
  src: string;
  tgt: string;
  count: number;
}

interface RecentJob {
  id: string;
  status: string;
  fileName: string;
  sourceLang: string;
  targetLang: string;
  createdAt: string;
  finishedAt?: string;
}

interface DashboardStats {
  glossary: { total: number; enabled: number };
  translationMemory: { total: number };
  jobs: { total: number; succeeded: number };
  langPairs: LangPair[];
  topTerms: TopTerm[];
  recentJobs: RecentJob[];
}

const STATUS_COLOR: Record<string, string> = {
  succeeded: "success",
  running: "processing",
  failed: "error",
  queued: "default",
};

const STATUS_LABEL: Record<string, string> = {
  succeeded: "完成",
  running: "翻译中",
  failed: "失败",
  queued: "排队中",
};

// ── Component ──────────────────────────────────────────────────────────────

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const data = await get<DashboardStats>("/dashboard/stats");
        setStats(data);
      } catch {
        // fail silently — dashboard is read-only
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "60vh" }}>
        <Spin size="large" />
      </div>
    );
  }

  // ── Top terms table ───────────────────────────────────────────────────────
  const termColumns: ColumnsType<TopTerm> = [
    {
      title: "排名",
      key: "rank",
      width: 56,
      render: (_: unknown, __: TopTerm, index: number) => (
        <Text type="secondary" style={{ fontFamily: "monospace" }}>{index + 1}</Text>
      ),
    },
    {
      title: "原文术语",
      dataIndex: "sourceTerm",
      key: "sourceTerm",
      render: (v: string) => <Text strong>{v}</Text>,
    },
    {
      title: "译文术语",
      dataIndex: "targetTerm",
      key: "targetTerm",
    },
    {
      title: "语言对",
      key: "lang",
      width: 120,
      render: (_: unknown, row: TopTerm) => (
        <Text type="secondary" style={{ fontSize: 12 }}>{row.sourceLang} → {row.targetLang}</Text>
      ),
    },
    {
      title: "匹配次数",
      dataIndex: "hitCount",
      key: "hitCount",
      width: 100,
      align: "right" as const,
      render: (v: number) => <Text style={{ fontFamily: "monospace", color: "#1b3a6b" }}>{v}</Text>,
    },
  ];

  // ── Recent jobs table ─────────────────────────────────────────────────────
  const jobColumns: ColumnsType<RecentJob> = [
    {
      title: "文件名",
      dataIndex: "fileName",
      key: "fileName",
      ellipsis: true,
      render: (v: string) => <Text>{v}</Text>,
    },
    {
      title: "翻译方向",
      key: "lang",
      width: 140,
      render: (_: unknown, row: RecentJob) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {row.sourceLang} → {row.targetLang}
        </Text>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 90,
      render: (v: string) => (
        <Tag color={STATUS_COLOR[v] ?? "default"}>{STATUS_LABEL[v] ?? v}</Tag>
      ),
    },
    {
      title: "提交时间",
      dataIndex: "createdAt",
      key: "createdAt",
      width: 170,
      render: (v: string) => (
        <Text style={{ fontSize: 12, fontFamily: "monospace" }}>
          {new Date(v).toLocaleString("zh-CN")}
        </Text>
      ),
    },
  ];

  return (
    <div style={{ padding: "0 0 24px" }}>
      {/* ── Summary stats ── */}
      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="术语库"
              value={stats?.glossary.total ?? 0}
              suffix="条"
              prefix={<DatabaseOutlined style={{ fontSize: 16, color: "#1b3a6b" }} />}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              启用 {stats?.glossary.enabled ?? 0} 条
            </Text>
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="翻译记忆"
              value={stats?.translationMemory.total ?? 0}
              suffix="段"
              prefix={<FileTextOutlined style={{ fontSize: 16, color: "#1b3a6b" }} />}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              已存入记忆库
            </Text>
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="翻译任务"
              value={stats?.jobs.total ?? 0}
              suffix="个"
              prefix={<TranslationOutlined style={{ fontSize: 16, color: "#1b3a6b" }} />}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              成功 {stats?.jobs.succeeded ?? 0} 个
            </Text>
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="成功率"
              value={
                stats && stats.jobs.total > 0
                  ? Math.round((stats.jobs.succeeded / stats.jobs.total) * 100)
                  : 0
              }
              suffix="%"
              prefix={<CheckCircleOutlined style={{ fontSize: 16, color: "#52c41a" }} />}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              QA 通过任务占比
            </Text>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        {/* ── Top terms ── */}
        <Col xs={24} lg={14}>
          <Card
            title="最常命中的术语"
            size="small"
            extra={
              <Text type="secondary" style={{ fontSize: 12 }}>
                基于翻译记忆库匹配次数排序
              </Text>
            }
          >
            {stats && stats.topTerms.length > 0 ? (
              <Table
                dataSource={stats.topTerms}
                columns={termColumns}
                rowKey={(r) => `${r.sourceLang}-${r.sourceTerm}`}
                size="small"
                pagination={{ pageSize: 10, showSizeChanger: false, size: "small" }}
                scroll={{ y: 320 }}
              />
            ) : (
              <div style={{ padding: "32px 0", textAlign: "center" }}>
                <Text type="secondary">暂无数据 — 完成翻译后术语命中数据将自动统计</Text>
              </div>
            )}
          </Card>
        </Col>

        {/* ── Right column: lang pairs + recent jobs ── */}
        <Col xs={24} lg={10}>
          <Row gutter={[0, 16]}>
            {/* Lang pairs */}
            <Col span={24}>
              <Card title="语言对分布" size="small">
                {stats && stats.langPairs.length > 0 ? (
                  <Table
                    dataSource={stats.langPairs}
                    rowKey={(r) => `${r.src}-${r.tgt}`}
                    size="small"
                    pagination={false}
                    columns={[
                      {
                        title: "语言对",
                        key: "pair",
                        render: (_: unknown, r: LangPair) => (
                          <Text>{r.src} → {r.tgt}</Text>
                        ),
                      },
                      {
                        title: "任务数",
                        dataIndex: "count",
                        key: "count",
                        width: 80,
                        align: "right" as const,
                        render: (v: number) => (
                          <Text style={{ fontFamily: "monospace", color: "#1b3a6b" }}>{v}</Text>
                        ),
                      },
                    ]}
                  />
                ) : (
                  <Text type="secondary" style={{ fontSize: 12 }}>暂无翻译任务数据</Text>
                )}
              </Card>
            </Col>

            {/* Recent jobs */}
            <Col span={24}>
              <Card title="最近翻译任务" size="small">
                {stats && stats.recentJobs.length > 0 ? (
                  <Table
                    dataSource={stats.recentJobs}
                    columns={jobColumns}
                    rowKey="id"
                    size="small"
                    pagination={false}
                    scroll={{ y: 200 }}
                  />
                ) : (
                  <Text type="secondary" style={{ fontSize: 12 }}>暂无翻译任务</Text>
                )}
              </Card>
            </Col>
          </Row>
        </Col>
      </Row>
    </div>
  );
}
