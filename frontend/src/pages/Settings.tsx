import { Typography, Card } from "antd";
import { InfoCircleOutlined } from "@ant-design/icons";
import { Space } from "antd";

const { Text, Paragraph } = Typography;

export default function Settings() {
  return (
    <div style={{ maxWidth: 720, margin: "0 auto" }}>
      <Card title="翻译引擎">
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
            <InfoCircleOutlined style={{ color: "#1b3a6b", marginTop: 3 }} />
            <div>
              <Text strong>术语强制对齐</Text>
              <Paragraph type="secondary" style={{ marginBottom: 0, marginTop: 4, fontSize: 13 }}>
                术语库中的词条在翻译时会自动注入提示词，确保前后一致。可在"术语库"页面管理词条和启用状态。
              </Paragraph>
            </div>
          </div>

          <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
            <InfoCircleOutlined style={{ color: "#1b3a6b", marginTop: 3 }} />
            <div>
              <Text strong>翻译批次策略</Text>
              <Paragraph type="secondary" style={{ marginBottom: 0, marginTop: 4, fontSize: 13 }}>
                系统按 5000 字节或 40 段为上限自动分批，单段超限时单独提交。可通过环境变量
                <Text code>TRANSLATION_BATCH_MAX_BYTES</Text> / <Text code>TRANSLATION_BATCH_MAX_SEGMENTS</Text> 调整。
              </Paragraph>
            </div>
          </div>

          <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
            <InfoCircleOutlined style={{ color: "#1b3a6b", marginTop: 3 }} />
            <div>
              <Text strong>翻译记忆</Text>
              <Paragraph type="secondary" style={{ marginBottom: 0, marginTop: 4, fontSize: 13 }}>
                每次翻译完成后，QA 通过的段落会自动存入翻译记忆库，可在"术语库"页面导出 CSV 查看。
              </Paragraph>
            </div>
          </div>
        </Space>
      </Card>
    </div>
  );
}
