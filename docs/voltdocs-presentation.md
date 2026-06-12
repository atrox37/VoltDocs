# VoltDocs 智能文档处理平台
## 项目介绍与技术讲解

---

# 第一章：项目背景与定位

## 1.1 为什么要做 VoltDocs

公司日常工作中存在大量文档处理需求：

- 工程手册、安装说明、BOM 表需要从**中文翻译成英文**发给海外团队或客户
- 技术文档在 Word、Markdown、Excel 之间频繁互转
- 不同业务人员对同一专业术语（如"逆变器"）的英文表达不统一，导致对外文件质量参差不齐
- 传统方式：人工翻译效率低，机翻质量差，且无法保证术语一致性

**VoltDocs 的目标：** 用 AI 完成重复性翻译工作，同时通过术语库保证专业词汇的一致性，让工程师专注于内容审校而非重复翻译。

## 1.2 核心能力

| 能力 | 说明 |
|------|------|
| 文档翻译 | Word (.docx)、Excel (.xlsx)、Markdown (.md) 多格式支持 |
| 文档转换 | Markdown ↔ Word 双向转换，支持公司 Word 模板 |
| 术语管理 | 维护中英术语对，翻译时强制 AI 使用指定术语 |
| 多用户协作 | 基于角色的权限控制（超级管理员 / 管理员 / 普通用户）|
| 翻译审校 | QA 自动检查 + 人工审校工作流 |

---

# 第二章：系统架构

## 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────┐
│                     用户浏览器                           │
│           React + Ant Design (前端)                      │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP/REST (反向代理)
┌──────────────────────▼──────────────────────────────────┐
│               Python FastAPI 后端                         │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  │ 翻译路由  │  │ 转换路由  │  │ 术语路由  │  │ 认证   │  │
│  └────┬─────┘  └────┬─────┘  └──────────┘  └────────┘  │
│       │              │                                    │
│  ┌────▼─────────┐  ┌─▼──────┐  ┌──────────────────────┐ │
│  │ 解析器层      │  │ Pandoc │  │     SQLite 数据库      │ │
│  │ docx/xlsx/md │  │ (转换)  │  │ (jobs/segments/术语表)│ │
│  └────┬─────────┘  └────────┘  └──────────────────────┘ │
│       │                                                   │
└───────┼───────────────────────────────────────────────────┘
        │ boto3 SDK
┌───────▼──────────────────┐
│   AWS Bedrock             │
│   Claude Sonnet 4.5       │
└───────────────────────────┘
```

## 2.2 技术栈选型

### 前端
- **React 18 + TypeScript** — 类型安全，便于维护
- **Ant Design 5** — 企业级 UI 组件库，开箱即用
- **Vite** — 极快的构建工具

### 后端
- **Python 3.12 + FastAPI** — 高性能异步框架，原生支持 async/await
- **SQLite + WAL 模式** — 单文件数据库，零运维，WAL 模式支持读写并发
- **lxml** — 高性能 XML 解析（用于 Word 文档的 XML 操作）
- **openpyxl / python-pptx** — Excel/PPT 文件处理
- **boto3** — AWS SDK，直连 Bedrock 调用 Claude

### AI 服务
- **AWS Bedrock + Claude Sonnet** — 托管大模型，按 token 计费，无需自建 GPU
- 直连模式：Python 后端通过 boto3 直接调用，绕过 Lambda，无 29 秒超时限制

### 部署
- **Docker + Nginx** — 容器化部署，nginx 反向代理前端和后端
- **AWS Cognito** — 企业级身份认证（与 Microsoft Teams/Azure AD 联动）

---

# 第三章：翻译功能详解

## 3.1 翻译流程全景

```
用户上传文件
    │
    ▼
格式检测 (docx / xlsx / md)
    │
    ▼
文件解析 → 提取 segments（段落/单元格/行）
    │
    ▼
从术语库加载匹配术语
    │
    ▼
按批次发给 Bedrock Claude 翻译
（5000字节 或 120段 为上限）
    │
    ▼
7条 QA 规则自动检查每个译文
    │
    ├── 全部通过 → 自动生成输出文件 → 用户直接下载
    │
    └── 有问题 → 进入审校界面 → 用户修改/确认 → 手动导出
```

## 3.2 三种格式的处理差异

### Word (.docx)
- **解析**：直接操作 ZIP 内的 `word/document.xml`（OOXML 格式）
- **格式保留**：将 `<w:b>/<w:i>/<w:strike>` 转为 `**text**/*text*/~~text~~` 发给 AI，AI 返回后还原为 XML 标签
- **图片保留**：翻译时保留原始 ZIP 内的所有图片（`word/media/` 目录），图片文件用 `ZIP_STORED` 不重新压缩
- **跳过**：代码样式段落（SourceCode/Verbatim）、纯数字/符号行

### Excel (.xlsx)
- **解析**：用 openpyxl 遍历所有可见 Sheet 的字符串单元格
- **格式保留**：直接在原始文件里按坐标替换单元格值，格式/样式/公式完全不动
- **跳过**：公式单元格、隐藏 Sheet、纯数字内容

### Markdown (.md)
- **解析**：逐行识别标题/段落/列表/引用块/表格，代码块不翻译
- **格式保留**：保留 `# ` 标题前缀、`- ` 列表前缀、`> ` 引用前缀
- **表格**：每个单元格独立为一个 segment，分隔行跳过

## 3.3 智能分批策略

翻译不是一次性把整个文档发给 AI，而是分批处理：

```
每批上限：
  - 5000 UTF-8 字节  (约 1600 汉字)
  - 或 120 个段落

单个段落超过 5000 字节 → 单独成一批（保证不卡死）

最大并发批次：5 个（同时发给 Bedrock）
```

**为什么要分批？**
- Lambda 的 API Gateway 有 29 秒超时，直连 Bedrock 虽然无此限制，但分批可以更细粒度更新进度
- 失败时只重试一批，不是整个文档
- 并发发送提高整体速度

## 3.4 术语强制对齐机制

这是保证翻译质量的核心机制：

**第一层：Prompt 注入（预防）**

每批翻译前，系统从术语库找出在这批段落原文里出现的术语，注入到 system prompt：

```
MANDATORY TERMINOLOGY — you MUST use these exact translations
whenever the source term appears. Do NOT paraphrase or substitute:
- 逆变器 → inverter
- 支架 → mounting bracket
- 太阳能 → solar
```

关键词是 **MANDATORY**（强制），而非之前的 "Reference"（参考）。

**第二层：QA 验证（事后检查）**

翻译返回后，QA 规则会检查：如果原文里有术语表里的词，译文里必须有对应的翻译。不符合就标记为 QA 失败，进入审校。

## 3.5 QA 检查规则（7条）

| # | 规则 | 举例 |
|---|------|------|
| 1 | 译文非空 | AI 返回空白 → 标记失败 |
| 2 | 数字一致性 | 原文"型号 AB-123"，译文里没有"123" → 失败 |
| 3 | 格式标记保留 | 原文有 `**重要**`，译文没有 `**` → 失败 |
| 4 | 长度比例 | 译文 < 8% 原文长度（截断）或 > 20× → 失败 |
| 5 | 语言漏出 | 中译英任务，译文 60%+ 还是中文 → 失败 |
| 6 | 术语一致性 | 原文含"逆变器"，译文没有"inverter" → 失败 |
| 7 | 标点一致性 | 英文译文以中文句号"。"结尾 → 失败 |

---

# 第四章：文档转换功能

## 4.1 Markdown ↔ Word 转换

底层使用 **Pandoc**（业界最成熟的文档转换工具）：

```
md → docx：
  pandoc input.md -o output.docx [--reference-doc template.docx]

docx → md：
  pandoc input.docx -o output.md
  （图片提取到 media/ 目录，打包成 zip 下载）
```

**模板支持：** 可以上传公司的标准 Word 模板（.docx），Pandoc 会用模板的样式表输出，保证标题字体、页边距、表格样式符合公司规范。

## 4.2 图片处理（docx → md）

Word 转 Markdown 时，pandoc 会把图片提取到 `media/` 目录。系统的处理方式：
1. 在临时工作目录执行转换
2. 检测是否有 `media/` 子目录
3. 有图片则打包成 `.zip`（md 文件 + media 目录）一起下载
4. 下载后解压，在 md 文件所在目录放好 media 文件夹，图片就能正常显示

---

# 第五章：权限与认证体系

## 5.1 三级角色

| 角色 | 权限 |
|------|------|
| super_admin（超级管理员）| 所有权限，含用户管理 |
| manager（管理员）| 翻译、转换、术语库管理、审计日志查看 |
| user（普通用户）| 翻译、转换、个人设置 |

## 5.2 认证流程（生产环境）

```
用户点击登录
    │
    ▼
跳转 AWS Cognito（与 Microsoft Teams 联动）
    │
    ▼
企业账号认证成功
    │
    ▼
Cognito 返回 Authorization Code
    │
    ▼
后端换取 Access Token + Refresh Token
    │
    ▼
创建 Session（存内存），写 Cookie
    │
    ▼
用户正常使用，每次请求验证 Session
```

**自动续期：** Access Token 有效期约 1 小时，剩余 5 分钟时后端自动用 Refresh Token 静默换新 Token，用户无感知。Session 本身 idle 4 小时或绝对 30 天后过期。

---

# 第六章：术语库管理

## 6.1 设计理念

**一套术语，双向使用。** 维护"逆变器 → inverter"，系统自动支持：
- 中译英：遇到"逆变器"强制用"inverter"
- 英译中：遇到"inverter"强制用"逆变器"

无需分别维护两份术语表。

## 6.2 支持的操作

| 操作 | 说明 |
|------|------|
| 单条新增 | 填写中文术语 + 英文术语 |
| 批量导入 | 上传 .xlsx 或 .csv，系统预览冲突（新增/替换/跳过）|
| 启用/禁用 | 可临时关闭某个术语而不删除 |
| 命中次数 | 显示历史翻译中该术语出现的次数 |

## 6.3 命中次数的统计逻辑

统计所有历史翻译段落（`job_segments` 表）的原文中包含该术语的次数。反映该术语在实际工作中的使用频率，帮助判断哪些术语最关键、最值得维护。

---

# 第七章：数据库设计

## 7.1 核心表结构

```
jobs（翻译/转换任务）
├── id, user_id, type, status, progress
├── input_file_id, output_file_id
├── payload_json（原始参数）
└── result_json（执行结果）

job_segments（翻译段落）
├── job_id, segment_id, segment_order
├── source_text（原文）
├── draft_translation（AI 初译）
├── qa_pass, qa_reason（QA 结果）
└── status（pending/translated/qa_failed）

glossary_terms（术语表）
├── source_lang, target_lang
├── source_term, target_term
├── enabled, priority
└── context（术语使用说明）

files（文件注册表）
├── kind（translation-input/translation-output/convert-input/...）
├── storage_path（磁盘路径）
└── sha256（文件指纹，防重复）

user_roles（用户角色）
└── email, role, last_login
```

---

# 第八章：部署架构

## 8.1 Docker Compose 部署

```yaml
services:
  api:   # Python FastAPI 后端，Port 8080
  web:   # React 前端 + Nginx，Port 8088（对外）
```

Nginx 反向代理：`/api/*` 转发给后端，其余请求返回前端静态文件（SPA 路由）。

## 8.2 数据持久化

```
/opt/voltdocs/data/
├── db/voltdocs.db      # SQLite 数据库
├── uploads/            # 用户上传的原始文件
├── outputs/            # 翻译/转换后的输出文件
└── templates/          # Word 模板文件
```

## 8.3 AWS 服务依赖

| 服务 | 用途 |
|------|------|
| Bedrock (Claude) | AI 翻译推理 |
| Cognito | 用户身份认证（生产环境）|
| IAM Role / Access Key | Bedrock 鉴权（建议用 IAM Role）|

---

# 第九章：使用场景示例

## 场景 A：翻译工厂安装手册

1. 进入「文档翻译」，拖入 `安装手册_V2.docx`
2. 选择 中文 → English，点击「开始翻译」
3. AI 翻译过程中进度条实时更新（按批次）
4. 翻译完成：
   - **全部 QA 通过** → 直接点「下载」
   - **有 QA 问题** → 点「审校」，针对问题段落逐一确认或修改
5. 导出的文档保留原始格式（标题样式、图片、表格、粗体/斜体）

## 场景 B：统一术语翻译

1. 进入「术语库」，批量导入公司标准术语表（.xlsx）
2. 再次翻译同类文档，AI 会强制使用术语表里的译法
3. 若 AI 未遵守，QA 自动标红，审校时一目了然

## 场景 C：Markdown 文档转 Word 提交

1. 进入「文档转换」，选择 `.md → Word`
2. 选择公司模板（已在模板中心上传）
3. 上传 Markdown 文件，点击「转换并下载 Word」
4. 下载的 Word 自动应用公司标准样式

---

# 第十章：关键设计决策与权衡

## 10.1 为什么选 SQLite 而不是 PostgreSQL？

- 公司内部工具，并发用户数有限（< 50 人同时使用）
- SQLite WAL 模式完全可以支撑
- **零运维**：不需要维护数据库服务，单文件备份
- 未来如果用户量增长，迁移到 PostgreSQL 只需替换驱动层

## 10.2 为什么直连 Bedrock 而不用 Lambda？

原架构通过 API Gateway → Lambda → Bedrock，存在问题：
- API Gateway 有 **29 秒超时**，长文档容易超时
- 多一跳延迟
- Token 认证复杂（需要将用户 token 透传给 Lambda）

直连后：
- 无超时限制（FastAPI 任务异步执行）
- 延迟更低
- 认证更简单（用 IAM Role 或 Access Key，不需要 Cognito token）

## 10.3 为什么用分批而不是一次发整个文档？

- Claude 的 output token 上限约 8192（Sonnet），大文档一次发完可能截断
- 分批后每批独立失败/重试，不影响其他批次
- 可以细粒度报告进度
- 长上下文下模型注意力会分散（"lost in the middle"现象），分批翻译质量更稳定

---

# 附录

## 技术选型对比

| 方案 | VoltDocs 选择 | 备选 | 选择理由 |
|------|--------------|------|---------|
| AI 服务 | AWS Bedrock Claude | OpenAI GPT | 公司 AWS 生态，数据合规 |
| 后端框架 | FastAPI | Express.js / Django | 异步原生支持，Python 生态丰富 |
| 数据库 | SQLite | PostgreSQL | 零运维，内部工具规模合适 |
| 认证 | AWS Cognito | 自建 JWT | 与企业 Microsoft 账号联动 |
| 文档转换 | Pandoc | LibreOffice | 命令行工具，Docker 容器友好 |

## 文件格式支持矩阵

| 格式 | 翻译 | 转换 | 图片保留 | 格式保留 |
|------|------|------|---------|---------|
| .docx | ✅ | ✅ (→md) | ✅ | ✅ |
| .xlsx | ✅ | ❌ | — | ✅ |
| .md | ✅ | ✅ (→docx) | — (转换时打包) | ✅ |

---

*文档版本：2026-06 / VoltDocs v1.0*
