import { Button, Card, Col, List, Progress, Row, Statistic, Tag, Typography } from "antd";
import {
  ArrowRightOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  SwapOutlined,
  SyncOutlined,
  TranslationOutlined,
} from "@ant-design/icons";
import { useNavigate } from "react-router-dom";

const { Title, Text } = Typography;

const modules = [
  { title: "文档转换", desc: ".md 与 Word 双向转换，支持模板化输出", icon: <SwapOutlined />, path: "/convert", stat: "本周 128 次" },
  { title: "文档翻译", desc: "支持 Word / Excel 双向翻译，翻译后进入个人审校", icon: <TranslationOutlined />, path: "/translate", stat: "进行中 3 个" },
  { title: "模板中心", desc: "上传和管理 Word 模板，统一导出版式", icon: <FileTextOutlined />, path: "/templates", stat: "1 个模板" },
  { title: "术语库", desc: "维护一套可双向使用的中英术语对", icon: <DatabaseOutlined />, path: "/memory", stat: "88 条术语" },
];

const recentTasks = [
  { name: "安装手册 v3.2.docx", type: "中文 -> English", time: "刚刚", status: "success" },
  { name: "BOM 清单.xlsx", type: "English -> 中文", time: "12 分钟前", status: "reviewing" },
  { name: "部署说明.docx", type: "Word -> .md", time: "1 小时前", status: "success" },
  { name: "项目说明.md", type: ".md -> Word", time: "今天 09:14", status: "success" },
];

export default function Dashboard() {
  const navigate = useNavigate();

  return (
    <div style={{ padding: 24 }}>
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="本月处理" value={342} suffix="份" />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="翻译字数" value="186K" suffix="字" />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="术语覆盖率" value={67} suffix="%" />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="平均耗时" value={12.4} suffix="分钟" />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        {modules.map((module) => (
          <Col xs={24} sm={12} lg={6} key={module.path}>
            <Card hoverable onClick={() => navigate(module.path)} style={{ height: "100%" }}>
              <div style={{ fontSize: 28, color: "#1b3a6b", marginBottom: 12 }}>{module.icon}</div>
              <Title level={5} style={{ marginBottom: 4 }}>
                {module.title}
              </Title>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {module.desc}
              </Text>
              <div style={{ marginTop: 12, fontSize: 11, color: "#999", fontFamily: "monospace" }}>{module.stat}</div>
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={8}>
          <Card title="术语使用情况" extra={<Button type="link" size="small" onClick={() => navigate("/memory")}>查看 <ArrowRightOutlined /></Button>}>
            <Statistic title="本周术语命中率" value={67} suffix="%" style={{ marginBottom: 16 }} />
            <div style={{ marginBottom: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>精确匹配</Text>
              <Progress percent={67} size="small" strokeColor="#1b3a6b" />
            </div>
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>补充匹配</Text>
              <Progress percent={32} size="small" strokeColor="#6b9fd4" />
            </div>
          </Card>
        </Col>
        <Col xs={24} lg={16}>
          <Card title="最近任务" extra={<Button type="link" size="small">查看全部 <ArrowRightOutlined /></Button>}>
            <List
              size="small"
              dataSource={recentTasks}
              renderItem={(item) => (
                <List.Item
                  extra={
                    item.status === "success" ? (
                      <Tag icon={<CheckCircleOutlined />} color="success">成功</Tag>
                    ) : (
                      <Tag icon={<SyncOutlined spin />} color="processing">审校中</Tag>
                    )
                  }
                >
                  <List.Item.Meta
                    avatar={<ClockCircleOutlined style={{ fontSize: 16, color: "#999" }} />}
                    title={<Text style={{ fontSize: 13 }}>{item.name}</Text>}
                    description={<Text type="secondary" style={{ fontSize: 11 }}>{item.type} · {item.time}</Text>}
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
