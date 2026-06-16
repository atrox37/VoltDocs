# VoltDocs

Voltage Energy 内部智能文档处理平台。支持 Word / Excel / Markdown 文档翻译、Markdown → Word 格式转换、术语库管理及多用户权限控制。

---

## 功能概览

| 功能 | 说明 |
|------|------|
| **文档翻译** | Word (.docx)、Excel (.xlsx)、Markdown (.md) 多格式翻译，保留原始格式 |
| **翻译审校** | AI 翻译后自动 QA + 修复；未通过项进入审校弹窗，人工确认后导出 |
| **文档转换** | Markdown → Word，支持公司 Word 模板 |
| **术语库** | 维护中英术语对，翻译与 QA 强制使用指定译法 |
| **模板中心** | 管理 Word 输出模板 |
| **用户与权限** | 三级角色（超级管理员 / 管理员 / 普通用户），AWS Cognito 认证 |
| **操作日志** | 关键操作记录，支持筛选 |

---

## 技术栈

| 层次 | 技术 |
|------|------|
| 前端 | React 18 + TypeScript + Ant Design 5 + Vite |
| 后端 | Python 3.12+ / FastAPI / SQLite (WAL) |
| AI 翻译 | AWS Bedrock Converse API（默认 Nova Lite） |
| QA / 修复 | 规则引擎 + Nova Micro 复核 + Nova Lite 批量修复 |
| 文档转换 | Pandoc |
| 认证 | AWS Cognito |
| 部署 | Docker Compose + Nginx |

---

## 项目结构

```
VoltDocs/
├── backend/                 # FastAPI 后端
│   ├── auth/                # Cognito 认证、Session
│   ├── routes/              # API 路由
│   ├── services/            # 解析、导出、翻译、QA
│   │   └── docx/            # DOCX 字段/目录/标记处理
│   ├── tests/               # pytest 测试
│   ├── main.py
│   ├── config.py
│   └── .env.example
├── frontend/                # React SPA
│   └── src/pages/           # Translate（含审校）、Convert、Memory 等
├── deploy/                  # 生产部署脚本与说明
├── docs/                    # 用户手册与归档文档
├── infra/nginx/             # 反向代理配置
└── docker-compose.yml
```

---

## 本地开发

### 前提

- Python 3.12+
- Node.js 20+、pnpm
- [Pandoc](https://pandoc.org/installing.html)（文档转换需要）
- AWS 凭证（Bedrock 调用权限，或配置 `BEDROCK_AWS_PROFILE`）

### 一键启动（推荐）

```bash
pnpm install          # 安装根目录 concurrently
cd frontend && pnpm install && cd ..

cp backend/.env.example backend/.env
# 编辑 backend/.env（本地开发可保持 REQUIRE_AUTH=false）

pnpm dev              # 同时启动后端 :8080 与前端 :5173
```

### 分别启动

```bash
# 后端
cd backend
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8080 --reload

# 前端
cd frontend && pnpm dev
```

前端开发服务器将 `/api/*` 代理到 `http://127.0.0.1:8080`。

### 测试

```bash
pnpm test
# 或：cd backend && python -m pytest tests/ -q
```

---

## 翻译流水线

```
上传 → 解析分段 → Bedrock 批量翻译 → 规则 QA
    → AI 修复（可配置轮次）→ 再次 QA → 写入任务结果
```

- **全部 QA 通过**：自动生成译文文件，文件列表可直接下载
- **存在 QA 问题**：状态为「需审校」；用户在审校弹窗中逐条/全部确认后点击「确定」保存，再在文件列表下载
- 支持重新审校并再次导出

---

## 环境变量

配置位于 `backend/.env`，模板见 `backend/.env.example`。

| 变量 | 默认 | 说明 |
|------|------|------|
| `PORT` | `8080` | 后端端口 |
| `DATA_DIR` | `./data` | 上传、输出、数据库目录 |
| `REQUIRE_AUTH` | `false` | 本地开发可关闭 Cognito |
| `BEDROCK_MODEL_ID` | `us.amazon.nova-lite-v1:0` | 翻译模型 |
| `QA_AI_MODEL_ID` | `us.amazon.nova-micro-v1:0` | QA 复核模型 |
| `QA_REPAIR_ENABLED` | `true` | 是否启用 AI 修复 |
| `QA_REPAIR_MAX_ATTEMPTS` | `1` | 修复轮次（建议 2） |
| `TRANSLATION_BATCH_MAX_SEGMENTS` | `40` | 每批翻译段落数 |
| `TRANSLATION_BATCH_MAX_BYTES` | `5000` | 每批翻译字节上限 |

完整列表以 `backend/config.py` 为准。AWS 凭证通过标准链（环境变量、`~/.aws/credentials` 或 `BEDROCK_AWS_PROFILE`）提供，无需在 `.env` 中硬编码密钥。

---

## QA 检查规则

| 类型 | 规则 |
|------|------|
| 硬规则 | 译文非空、格式标记、术语表、XML 泄漏 |
| 软规则 | 数字一致、长度比例、语言检测、标点、段落错位（可由 AI 复核） |

修复策略：格式标记 → 规则修复；空译文 / 术语 / 错位 → AI 批量修复；仍未通过 → 人工审校。

---

## 生产部署

详见 [deploy/README.md](deploy/README.md)。

```bash
cp backend/.env.example backend/.env   # 填写生产配置
sudo bash deploy/setup-https.sh
```

---

## 文档

| 文档 | 说明 |
|------|------|
| [backend/README.md](backend/README.md) | 后端开发与结构 |
| [deploy/README.md](deploy/README.md) | 生产部署 |
| [docs/voltdocs-user-guide.md](docs/voltdocs-user-guide.md) | 用户使用手册 |
| [docs/archive/](docs/archive/) | 历史规划文档（仅供参考） |

---

## 术语库导入

Excel / CSV，表头示例：

| 中文术语 | 英文术语 |
|---------|---------|
| 逆变器 | inverter |
| 地脚 | Base Foot |

---

## 许可

Voltage Energy Internal — 仅供公司内部使用
