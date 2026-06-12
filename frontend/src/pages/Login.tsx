import { useMemo, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { Alert, Button, Card, Flex, Space, Spin, Typography } from "antd";
import { CloudSyncOutlined, DatabaseOutlined, LockOutlined } from "@ant-design/icons";
import { useAuth } from "../contexts/AuthContext";
import { getLoginUrl } from "../api/auth";
import BrandIcon from "../components/BrandIcon";

const { Title, Text, Paragraph, Link } = Typography;

function MicrosoftLogo() {
  return (
    <svg viewBox="0 0 23 23" aria-hidden="true" className="voltdocs-login-ms-logo">
      <rect x="1" y="1" width="10" height="10" fill="#F25022" />
      <rect x="12" y="1" width="10" height="10" fill="#7FBA00" />
      <rect x="1" y="12" width="10" height="10" fill="#00A4EF" />
      <rect x="12" y="12" width="10" height="10" fill="#FFB900" />
    </svg>
  );
}

function BrandMark() {
  return (
    <div className="voltdocs-login-brandmark">
      <BrandIcon size={40} className="voltdocs-login-brandmark-image" style={{ borderRadius: 8 }} />
    </div>
  );
}

export default function Login() {
  const { user, loading } = useAuth();
  const [searchParams] = useSearchParams();
  const [redirecting, setRedirecting] = useState(false);

  const error = searchParams.get("error");

  const featureItems = useMemo(
    () => [
      {
        icon: <CloudSyncOutlined />,
        text: ".md 与 Word 双向互转，模板化输出更稳定。",
      },
      {
        icon: <DatabaseOutlined />,
        text: "术语、任务和审校记录统一留存在当前系统中。",
      },
      {
        icon: <LockOutlined />,
        text: "企业 Microsoft 账号单点登录，接入 Cognito 鉴权。",
      },
    ],
    []
  );

  const handleLogin = async () => {
    setRedirecting(true);
    try {
      const { url } = await getLoginUrl();
      window.location.href = url;
    } catch {
      setRedirecting(false);
    }
  };

  if (loading) {
    return (
      <div className="voltdocs-login-loading">
        <Spin size="large" />
      </div>
    );
  }

  if (user) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="voltdocs-login-shell">
      <div className="voltdocs-login-mesh" />

      <aside className="voltdocs-login-hero">
        <div className="voltdocs-login-hero-glow voltdocs-login-hero-glow-left" />
        <div className="voltdocs-login-hero-glow voltdocs-login-hero-glow-right" />

        <div className="voltdocs-login-brand">
          <BrandMark />
          <div>
            <Title level={4} className="voltdocs-login-brand-title">
              VoltDocs
            </Title>
            <Text className="voltdocs-login-brand-subtitle">Voltage Internal</Text>
          </div>
        </div>

        <div className="voltdocs-login-hero-copy">
          <Title className="voltdocs-login-hero-title">
            让每一份文档，
            <br />
            交付得更稳。
          </Title>
          <Paragraph className="voltdocs-login-hero-desc">
            在一个工作台里完成文档转换、模板化输出、双向翻译和人工审校，
            更适合内部技术文档的整理与交付。
          </Paragraph>
        </div>

        <div className="voltdocs-login-features">
          {featureItems.map((item) => (
            <div key={item.text} className="voltdocs-login-feature">
              <div className="voltdocs-login-feature-icon">{item.icon}</div>
              <Text className="voltdocs-login-feature-text">{item.text}</Text>
            </div>
          ))}
        </div>

        <Text className="voltdocs-login-version">VoltDocs Web Workbench</Text>
      </aside>

      <main className="voltdocs-login-panel-wrap">
        <Card bordered={false} className="voltdocs-login-panel">
          <Space direction="vertical" size={24} style={{ width: "100%" }}>
            <div className="voltdocs-login-mobile-brand">
              <BrandMark />
              <div>
                <Title level={4} className="voltdocs-login-brand-title">
                  VoltDocs
                </Title>
                <Text className="voltdocs-login-brand-subtitle">Workbench</Text>
              </div>
            </div>

            <div>
              <Title level={2} className="voltdocs-login-panel-title">
                欢迎回到 VoltDocs
              </Title>
              <Text className="voltdocs-login-panel-subtitle">技术文档转换与翻译工作台</Text>
            </div>

            {error === "auth_failed" && (
              <Alert
                type="error"
                message="登录失败"
                description="Microsoft 账户认证未能完成，请重试。"
                showIcon
              />
            )}

            {error === "session_expired" && (
              <Alert
                type="warning"
                message="会话已过期"
                description="当前登录状态已经失效，请重新登录。"
                showIcon
              />
            )}

            <Flex vertical gap={10}>
              <Button
                type="primary"
                size="large"
                className="voltdocs-login-action"
                onClick={handleLogin}
                loading={redirecting}
              >
                {!redirecting && <MicrosoftLogo />}
                <span>{redirecting ? "正在跳转 Microsoft 登录..." : "使用 Microsoft 账号登录"}</span>
              </Button>

              <Text className="voltdocs-login-action-desc">企业 Azure AD 账号 · 单点登录</Text>
            </Flex>

            <div className="voltdocs-login-meta">
              <div className="voltdocs-login-meta-item">
                <DatabaseOutlined />
                <Text>文档、模板和翻译记录统一在 VoltDocs 中管理</Text>
              </div>

              <Text className="voltdocs-login-terms">
                登录即表示同意{" "}
                <Link href="#" onClick={(e) => e.preventDefault()}>
                  服务条款与隐私政策
                </Link>
              </Text>
            </div>
          </Space>
        </Card>
      </main>
    </div>
  );
}
