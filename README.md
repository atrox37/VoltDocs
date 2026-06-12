# VoltDocs

Voltage Energy 内部智能文档处理平台。支持 Word / Excel / Markdown 文档翻译、Markdown → Word 格式转换、术语库管理及多用户权限控制。

---

## 功能概览

| 功能 | 说明 |
|------|------|
| **文档翻译** | Word (.docx)、Excel (.xlsx)、Markdown (.md) 多格式翻译，保留原始格式 |
| **文档转换** | Markdown → Word 转换，支持公司 Word 模板 |
| **术语库** | 维护中英术语对，翻译时强制 AI 使用指定术语；支持批量导入/导出 |
| **翻译审校** | AI 翻译后自动 QA 检查（7 项规则），问题段落进入审校界面 |
| **模板中心** | 管理 Word 输出模板，支持标注语言和标签 |
| **用户管理** | 三级角色（超级管理员 / 管理员 / 普通用户），与 AWS Cognito 联动 |
| **操作日志** | 记录所有关键操作，支持筛选和导出 |

---

## 技术栈

| 层次 | 技术 |
|------|------|
| 前端 | React 18 + TypeScript + Ant Design 5 + Vite |
| 后端 | Python 3.12 + FastAPI + SQLite (WAL) |
| AI 翻译 | AWS Bedrock (Claude Haiku 4.5) via boto3 直连 |
| 文档转换 | Pandoc |
| 认证 | AWS Cognito (Microsoft Teams OIDC 联动) |
| 部署 | Docker Compose + Nginx |

---

## 项目结构

```
VoltDocs/
├── backend/              # Python FastAPI 后端
│   ├── auth/             # Cognito 认证、Session 管理
│   ├── routes/           # API 路由（翻译、转换、术语、用户等）
│   ├── services/         # 业务逻辑（解析器、导出器、QA、Bedrock）
│   ├── main.py           # FastAPI 应用入口
│   ├── database.py       # SQLite 数据库初始化
│   ├── config.py         # 配置加载（读取 .env）
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── .env.example      # 配置模板
│   └── .env              # 实际配置（不提交到 git）
├── frontend/             # React 前端
│   ├── src/
│   │   ├── pages/        # 各功能页面
│   │   ├── api/          # API 客户端
│   │   ├── layouts/      # 布局组件
│   │   └── contexts/     # 全局状态（Auth）
│   ├── Dockerfile
│   └── package.json
├── infra/
│   └── nginx/
│       └── default.conf  # Nginx 反向代理配置
├── deploy/
│   ├── setup-https.sh    # 一键部署脚本
│   └── README.md         # 详细部署说明
├── docs/                 # 项目文档
└── docker-compose.yml    # 生产部署编排文件
```

---

## 本地开发

### 前提

- Python 3.12+
- Node.js 20+
- [Pandoc](https://pandoc.org/installing.html)（文档转换功能需要）
- AWS 账号（有 Bedrock 调用权限）

### 1. 启动后端

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

# 复制配置文件
cp .env.example .env
# 编辑 .env，至少填写 AWS 凭证（开发模式可以设置 REQUIRE_AUTH=false）

python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

后端运行在：http://localhost:8080

### 2. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端运行在：http://localhost:5173

前端开发服务器已配置代理，`/api/*` 请求自动转发到后端 8080 端口。

---

## 环境变量说明

配置文件位于 `backend/.env`，参考 `backend/.env.example`：

### 基础配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `8080` | 后端监听端口 |
| `DATA_DIR` | `./data` | 数据存储目录（上传文件、数据库等）|
| `MAX_UPLOAD_MB` | `50` | 最大上传文件大小 |
| `PANDOC_PATH` | `pandoc` | Pandoc 可执行文件路径 |

### AI 翻译配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TRANSLATION_LAMBDA_URL` | 空 | Lambda 翻译服务地址（空则直连 Bedrock）|
| `BEDROCK_MODEL_ID` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Bedrock 模型 ID |
| `BEDROCK_REGION` | `us-east-1` | AWS 区域 |
| `AWS_ACCESS_KEY_ID` | - | AWS 访问密钥 ID |
| `AWS_SECRET_ACCESS_KEY` | - | AWS 访问密钥 Secret |
| `TRANSLATION_BATCH_MAX_BYTES` | `5000` | 每批翻译最大字节数 |
| `TRANSLATION_BATCH_MAX_SEGMENTS` | `120` | 每批翻译最大段落数 |

### 认证配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `REQUIRE_AUTH` | `false` | 是否启用 Cognito 认证（本地开发设 `false`）|
| `DEV_USER_EMAIL` | `dev@voltdocs.local` | `REQUIRE_AUTH=false` 时注入的用户 |
| `INITIAL_ADMIN_EMAIL` | - | 启动时自动创建的超级管理员邮箱 |
| `COGNITO_DOMAIN` | - | Cognito 用户池域名 |
| `COGNITO_CLIENT_ID` | - | Cognito 应用客户端 ID |
| `COGNITO_CLIENT_SECRET` | - | Cognito 应用客户端 Secret（无则留空）|
| `COGNITO_REDIRECT_URI` | - | 认证回调地址（必须与 Cognito 控制台一致）|
| `FRONTEND_URL` | `http://localhost:5173` | 前端访问地址（用于认证跳转）|

---

## 生产部署

### 服务器要求

- 虚拟机：Ubuntu 20.04+，2 核 4GB 内存以上
- 部署架构：`用户 → 网关机 192.168.30.10:18088 → 虚拟机:8088`

### 快速部署

```bash
# 1. 上传代码到虚拟机
git clone <仓库地址> /opt/voltdocs/app
cd /opt/voltdocs/app

# 2. 填写生产配置
cp backend/.env.example backend/.env
nano backend/.env
# 关键配置：REQUIRE_AUTH=true, 填入 AWS 凭证和 Cognito 配置

# 3. 运行部署脚本
sudo bash deploy/setup-https.sh
```

脚本会自动安装 Docker、构建镜像、启动服务，并输出访问地址。

详细说明见 [deploy/README.md](deploy/README.md)。

---

## 数据目录

后端运行时数据写入 `DATA_DIR`（生产环境挂载为 Docker 卷 `/opt/voltdocs/data`）：

```
data/
├── db/
│   └── voltdocs.db       # SQLite 数据库（术语表、任务记录等）
├── uploads/              # 用户上传的原始文件
├── outputs/              # 翻译/转换后的输出文件
├── templates/            # Word 模板文件
└── jobs/                 # 任务临时文件
```

**不要将运行时数据放入 Docker 镜像，始终通过卷挂载。**

---

## 术语库导入格式

支持 `.xlsx` 和 `.csv` 格式，最简单的表头：

| 中文术语 | 英文术语 |
|---------|---------|
| 逆变器 | inverter |
| 折叠支架 | folding bracket |

完整可用表头见 [术语导入说明](#)。导出的 CSV 可直接修改后重新导入。

---

## QA 检查规则

翻译完成后每个段落自动执行 7 项检查：

1. **译文非空** — 确保 AI 没有漏译
2. **数字一致** — 原文中的数字必须出现在译文中
3. **格式标记保留** — `**粗体**` / `*斜体*` / `~~删除线~~` 标记不能丢失
4. **长度比例** — 译文不能比原文短 92% 或长 20 倍
5. **语言正确** — 目标语言与实际输出语言一致
6. **术语一致** — 术语库中的词必须按规定翻译
7. **标点规范** — 英文译文不用中文标点，反之亦然

---

## 许可

Voltage Energy Internal — 仅供公司内部使用
