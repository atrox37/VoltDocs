import { useEffect, useMemo, useState } from "react";
import {
  App,
  Button,
  Card,
  DatePicker,
  Empty,
  Progress,
  Select,
  Space,
  Typography,
} from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import {
  getQualityQa,
  getQualitySummary,
  getQualityTm,
  type KeyCountItem,
  type QualityFilterOptions,
  type QualityFilters,
  type QualityQaResponse,
  type QualitySummaryResponse,
  type QualityTmResponse,
} from "@/api/quality";

const { RangePicker } = DatePicker;
const { Text, Title } = Typography;

function formatLabel(value: string): string {
  const labelMap: Record<string, string> = {
    terminology: "术语",
    numbers: "数字",
    formatting: "格式",
    language_leak: "语言泄漏",
    alignment: "对齐",
    other: "其他",
    check_required_terms: "术语检查",
    check_numeric_consistency: "数字一致性",
    check_empty: "空译文",
    check_length_ratio: "长度比例",
    check_source_language_leak: "源语言泄漏",
    check_target_language_leak: "目标语言泄漏",
    check_segment_alignment: "段落对齐",
    check_inline_markers: "标记检查",
    check_repeated_punctuation: "标点重复",
    human_confirmed: "人工确认",
    qa_passed_clean: "QA 通过",
    model_generated: "模型生成",
    repaired_or_risky: "修复或风险",
    document: "文档",
    filetype: "文件类型",
    global: "全局",
  };
  return labelMap[value] ?? value;
}

function formatShortDate(value: string): string {
  return dayjs(value).format("MM-DD");
}

function buildLinePath(values: number[], width: number, height: number): string {
  if (values.length === 0) {
    return "";
  }
  const max = Math.max(...values, 1);
  const stepX = values.length > 1 ? width / (values.length - 1) : width;
  return values
    .map((value, index) => {
      const x = index * stepX;
      const y = height - (value / max) * height;
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

function TrendCard({
  title,
  subtitle,
  data,
  stroke,
}: {
  title: string;
  subtitle: string;
  data: Array<{ label: string; value: number }>;
  stroke: string;
}) {
  const width = 520;
  const height = 160;
  const values = data.map((item) => item.value);
  const path = buildLinePath(values, width, height);
  const latest = values.at(-1) ?? 0;
  const peak = values.length > 0 ? Math.max(...values) : 0;

  return (
    <Card
      size="small"
      title={title}
      styles={{ body: { padding: 16, display: "flex", flexDirection: "column", gap: 12, height: "100%" } }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
        <div>
          <div style={{ fontSize: 28, fontWeight: 700, lineHeight: 1 }}>{latest}</div>
          <Text type="secondary">{subtitle}</Text>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 12, color: "#6b7280" }}>峰值</div>
          <div style={{ fontSize: 20, fontWeight: 600 }}>{peak}</div>
        </div>
      </div>

      {data.length === 0 ? (
        <div style={{ flex: 1, display: "grid", placeItems: "center" }}>
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无趋势数据" />
        </div>
      ) : (
        <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", gap: 10 }}>
          <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "100%", minHeight: 140 }}>
            <path d={path} fill="none" stroke={stroke} strokeWidth="3" strokeLinecap="round" />
            {values.map((value, index) => {
              const x = values.length > 1 ? (index * width) / (values.length - 1) : width / 2;
              const y = height - (value / Math.max(...values, 1)) * height;
              return <circle key={`${data[index]?.label ?? index}`} cx={x} cy={y} r="4" fill={stroke} />;
            })}
          </svg>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {formatShortDate(data[0].label)}
            </Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {formatShortDate(data[data.length - 1].label)}
            </Text>
          </div>
        </div>
      )}
    </Card>
  );
}

function DistributionCard({
  title,
  items,
  emptyText,
  color,
}: {
  title: string;
  items: KeyCountItem[];
  emptyText: string;
  color: string;
}) {
  const total = items.reduce((sum, item) => sum + item.count, 0);

  return (
    <Card
      size="small"
      title={title}
      styles={{ body: { padding: 16, display: "flex", flexDirection: "column", gap: 10, height: "100%" } }}
    >
      {items.length === 0 ? (
        <div style={{ flex: 1, display: "grid", placeItems: "center" }}>
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} />
        </div>
      ) : (
        items.slice(0, 6).map((item) => {
          const percent = total > 0 ? Math.round((item.count / total) * 100) : 0;
          return (
            <div key={item.key}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 4 }}>
                <Text style={{ fontSize: 12 }}>{formatLabel(item.key)}</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {item.count} / {percent}%
                </Text>
              </div>
              <Progress percent={percent} strokeColor={color} size="small" showInfo={false} />
            </div>
          );
        })
      )}
    </Card>
  );
}

function OverviewCard({
  title,
  value,
  hint,
  accent,
}: {
  title: string;
  value: number;
  hint: string;
  accent: string;
}) {
  return (
    <Card
      size="small"
      styles={{
        body: {
          padding: 18,
          borderTop: `3px solid ${accent}`,
          display: "flex",
          flexDirection: "column",
          gap: 10,
          height: "100%",
        },
      }}
    >
      <Text type="secondary" style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: 0.8 }}>
        {title}
      </Text>
      <div style={{ fontSize: 34, fontWeight: 700, lineHeight: 1 }}>{value}</div>
      <Text type="secondary" style={{ fontSize: 12 }}>
        {hint}
      </Text>
    </Card>
  );
}

export default function QualityDashboard() {
  const { message } = App.useApp();
  const [filters, setFilters] = useState<QualityFilters>({});
  const [filterOptions, setFilterOptions] = useState<QualityFilterOptions>({
    users: [],
    fileTypes: [],
    languagePairs: [],
  });
  const [summary, setSummary] = useState<QualitySummaryResponse["summary"] | null>(null);
  const [qaData, setQaData] = useState<QualityQaResponse | null>(null);
  const [tmData, setTmData] = useState<QualityTmResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchData = async (nextFilters = filters) => {
    setLoading(true);
    try {
      const [summaryRes, qaRes, tmRes] = await Promise.all([
        getQualitySummary(nextFilters),
        getQualityQa(nextFilters),
        getQualityTm(nextFilters),
      ]);
      setFilterOptions(summaryRes.filters);
      setSummary(summaryRes.summary);
      setQaData(qaRes);
      setTmData(tmRes);
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : "Failed to load quality dashboard");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchData();
  }, []);

  const languagePairOptions = useMemo(
    () =>
      filterOptions.languagePairs.map((pair) => ({
        label: `${pair.sourceLang} -> ${pair.targetLang}`,
        value: `${pair.sourceLang}|${pair.targetLang}`,
      })),
    [filterOptions.languagePairs],
  );

  const qaTrend = useMemo(
    () => (qaData?.trend ?? []).slice(-10).map((item) => ({ label: item.date, value: item.count })),
    [qaData],
  );
  const tmTrend = useMemo(
    () => (tmData?.trend ?? []).slice(-10).map((item) => ({ label: item.date, value: item.hits })),
    [tmData],
  );

  return (
    <div
      style={{
        height: "100%",
        display: "flex",
        flexDirection: "column",
        gap: 16,
        overflow: "hidden",
      }}
    >
      <Card
        size="small"
        style={{
          zIndex: 10,
          borderRadius: 16,
          boxShadow: "0 10px 30px rgba(15, 23, 42, 0.08)",
        }}
        styles={{ body: { padding: 16 } }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <Title level={5} style={{ margin: 0 }}>
              质量概览
            </Title>
            <Text type="secondary">固定顶部筛选，滚动查看下方 QA 与 TM 指标</Text>
          </div>

          <Space size={[12, 12]} wrap>
            <RangePicker
              value={[
                filters.dateFrom ? dayjs(filters.dateFrom) : null,
                filters.dateTo ? dayjs(filters.dateTo) : null,
              ]}
              onChange={(dates) => {
                setFilters((prev) => ({
                  ...prev,
                  dateFrom: dates?.[0]?.format("YYYY-MM-DD"),
                  dateTo: dates?.[1]?.format("YYYY-MM-DD"),
                }));
              }}
            />
            <Select
              allowClear
              placeholder="文件类型"
              style={{ width: 140 }}
              value={filters.fileType}
              options={filterOptions.fileTypes.map((value) => ({ label: value, value }))}
              onChange={(value) => {
                setFilters((prev) => ({ ...prev, fileType: value }));
              }}
            />
            <Select
              allowClear
              placeholder="语言方向"
              style={{ width: 180 }}
              value={
                filters.sourceLang && filters.targetLang
                  ? `${filters.sourceLang}|${filters.targetLang}`
                  : undefined
              }
              options={languagePairOptions}
              onChange={(value) => {
                if (!value) {
                  setFilters((prev) => ({ ...prev, sourceLang: undefined, targetLang: undefined }));
                  return;
                }
                const [sourceLang, targetLang] = value.split("|");
                setFilters((prev) => ({ ...prev, sourceLang, targetLang }));
              }}
            />
            <Select
              allowClear
              showSearch
              placeholder="提交人"
              style={{ width: 220 }}
              value={filters.userEmail}
              options={filterOptions.users.map((value) => ({ label: value, value }))}
              onChange={(value) => {
                setFilters((prev) => ({ ...prev, userEmail: value }));
              }}
            />
            <Button
              onClick={() => {
                const cleared = {};
                setFilters(cleared);
                void fetchData(cleared);
              }}
            >
              重置
            </Button>
            <Button
              type="primary"
              icon={<ReloadOutlined />}
              loading={loading}
              onClick={() => void fetchData(filters)}
            >
              刷新
            </Button>
          </Space>
        </div>
      </Card>

      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflow: "auto",
          paddingRight: 4,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 16, minHeight: "100%" }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(12, minmax(0, 1fr))",
              gap: 16,
            }}
          >
            <div style={{ gridColumn: "span 3", minHeight: 0 }}>
              <OverviewCard
                title="翻译任务数"
                value={summary?.jobTotal ?? 0}
                hint="当前筛选范围内的任务总数"
                accent="#2563eb"
              />
            </div>
            <div style={{ gridColumn: "span 3", minHeight: 0 }}>
              <OverviewCard
                title="分段总数"
                value={summary?.segmentTotal ?? 0}
                hint="已处理的译文分段总数"
                accent="#0f766e"
              />
            </div>
            <div style={{ gridColumn: "span 3", minHeight: 0 }}>
              <OverviewCard
                title="QA 失败数"
                value={summary?.qaFailedSegments ?? 0}
                hint={`失败率 ${summary?.qaFailureRate ?? 0}%`}
                accent="#d97706"
              />
            </div>
            <div style={{ gridColumn: "span 3", minHeight: 0 }}>
              <OverviewCard
                title="TM 记录数"
                value={summary?.tmRecordTotal ?? 0}
                hint={`人工确认 ${summary?.tmHumanConfirmedTotal ?? 0} / 风险 ${summary?.tmRiskyTotal ?? 0}`}
                accent="#7c3aed"
              />
            </div>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(12, minmax(0, 1fr))",
              gap: 16,
            }}
          >
            <div style={{ gridColumn: "span 6", minHeight: 0 }}>
              <TrendCard title="QA 趋势" subtitle="每日失败分段数" data={qaTrend} stroke="#2563eb" />
            </div>
            <div style={{ gridColumn: "span 6", minHeight: 0 }}>
              <TrendCard title="TM 趋势" subtitle="每日 TM 命中数" data={tmTrend} stroke="#16a34a" />
            </div>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(12, minmax(0, 1fr))",
              gap: 16,
              alignItems: "start",
            }}
          >
            <div style={{ gridColumn: "span 3", minHeight: 0 }}>
              <DistributionCard
                title="失败类型分布"
                items={qaData?.failureTypes ?? []}
                emptyText="暂无 QA 失败数据"
                color="#2563eb"
              />
            </div>
            <div style={{ gridColumn: "span 3", minHeight: 0 }}>
              <DistributionCard
                title="QA 规则分布"
                items={qaData?.rules ?? []}
                emptyText="暂无 QA 规则数据"
                color="#f59e0b"
              />
            </div>
            <div style={{ gridColumn: "span 3", minHeight: 0 }}>
              <DistributionCard
                title="TM 质量分层"
                items={tmData?.qualityTiers ?? []}
                emptyText="暂无 TM 质量数据"
                color="#16a34a"
              />
            </div>
            <div style={{ gridColumn: "span 3", minHeight: 0 }}>
              <DistributionCard
                title="TM 作用域分布"
                items={tmData?.scopeFamilies ?? []}
                emptyText="暂无 TM 作用域数据"
                color="#0891b2"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
