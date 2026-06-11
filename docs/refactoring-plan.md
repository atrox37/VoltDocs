# VoltDocs 前后端拆分重构方案

> 日期：2026-06-04  
> 目标：将 Tauri 桌面应用（DocumentConversionTool）的核心能力拆分为 **Web 前端 + Rust 后端（Actix-Web）** 的单服务器架构  
> 后端已重写为 Rust，复用 Tauri 版的 DOCX 解析/导出核心代码，位于 `backend-rs/`

---

## 一、架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                        浏览器 (React SPA)                       │
│  next-react-app 的 UI 壳子 + API 调用层                         │
│  Vite + React 18 + shadcn/ui + TanStack Query + i18n           │
└─────────────────────┬───────────────────────────────────────────┘
                      │  HTTP REST API (JSON + multipart)
                      │  可选 SSE 推送翻译进度
┌─────────────────────▼───────────────────────────────────────────┐
│                   Node.js 后端 (Express)                         │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │  路由层                                                    │ │
│  │  /api/convert  /api/translation  /api/glossary            │ │
│  │  /api/templates  /api/reviews  /api/files  /api/settings  │ │
│  └───────────────────────────────┬───────────────────────────┘ │
│                                  │                              │
│  ┌───────────────────────────────▼───────────────────────────┐ │
│  │  服务层                                                    │ │
│  │  docxParser.ts     格式标记提取（SAX 解析）                  │ │
│  │  docxExporter.ts   译文写回 + 格式还原                       │ │
│  │  translation.ts    分块并发翻译 + QA                         │ │
│  │  pandoc.ts         pandoc 子进程 + Lua 过滤器                │ │
│  │  glossaryMatcher   术语匹配注入                              │ │
│  │  jobs.ts           异步任务队列                              │ │
│  └───────────────────────────────┬───────────────────────────┘ │
│                                  │                              │
│  ┌───────────────┐  ┌────────────▼────────┐  ┌──────────────┐ │
│  │  SQLite       │  │  本地文件系统        │  │  pandoc      │ │
│  │  术语表/TM/   │  │  data/uploads/      │  │  (apt 安装)  │ │
│  │  Job/审校记录 │  │  data/templates/    │  │              │ │
│  │              │  │  data/outputs/      │  │              │ │
│  └───────────────┘  └─────────────────────┘  └──────────────┘ │
│                                                                 │
│                      │  HTTPS（可选）                           │
└──────────────────────┼──────────────────────────────────────────┘
                       ▼
          ┌─────────────────────────┐
          │  AWS Lambda (现有)       │
          │  AI 翻译 (Bedrock)       │
          │  可选：直连 Bedrock SDK  │
          └─────────────────────────┘
```

### 核心决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 部署形态 | 单服务器（Docker Compose） | 你的场景是内部工具，不需要分布式 |
| 文档解析 | Node.js 侧 SAX 解析（fast-xml-parser）| 复用 Rust 的解析逻辑，JS 已有等效库 |
| 格式转换 | pandoc（apt 安装到容器） | 与 Tauri 版等效，已验证可行 |
| 术语表 | 本地 SQLite | 单服务器直接本地读写，无需 DynamoDB |
| 模板存储 | 本地文件系统 `data/templates/` | 单服务器无需 S3，文件直接存磁盘 |
| 翻译记忆 | 本地 SQLite | 与 Tauri 版表结构一致 |
| AI 翻译 | 继续调 Lambda 或直连 Bedrock SDK | Lambda 已部署可用；后续可切换为直连 |
| 认证 | JWT（开发阶段可关闭） | 保留 Cognito 兼容，但单机可用 mock 用户 |
| 进度推送 | SSE (Server-Sent Events) | 比 WebSocket 简单，单向推送够用 |

---

## 二、后端模块拆分（对应 Tauri Rust 代码）

### 2.1 文件结构规划

```
backend/src/
├── config.ts                    # 配置（已有）
├── server.ts                    # Express 入口（已有）
├── middleware.ts                # Auth + 异步错误处理（已有）
├── db/
│   └── database.ts              # SQLite 初始化 + 迁移（已有，需补表）
├── routes/
│   ├── convert.ts               # 格式转换路由（已有，需增强）
│   ├── translation.ts           # 翻译路由（已有，需增强）
│   ├── glossary.ts              # 术语表路由（已有，完善）
│   ├── templates.ts             # 模板路由（已有，完善）
│   ├── reviews.ts               # 审校路由（已有，需增强）
│   ├── files.ts                 # 文件下载路由（已有）
│   ├── settings.ts              # 设置路由（新增）
│   └── tm.ts                    # 翻译记忆路由（新增）
├── services/
│   ├── docxParser.ts            # ★ DOCX SAX 解析（新增，对标 Rust extract_word_segments）
│   ├── docxExporter.ts          # ★ DOCX 译文写回（新增，对标 Rust patch_docx_translations）
│   ├── translation.ts           # 翻译调用逻辑（已有，需改造分块并发）
│   ├── pandoc.ts                # pandoc 调用（已有，需增强 Lua 过滤器）
│   ├── glossaryMatcher.ts       # 术语匹配（已有，完善）
│   ├── jobs.ts                  # Job 队列（已有）
│   ├── fileRegistry.ts          # 文件注册表（已有）
│   ├── storage.ts               # 存储工具（已有）
│   ├── tm.ts                    # 翻译记忆库（新增，对标 Rust translation_memory.rs）
│   ├── docxSecurity.ts          # 加密检测（新增，对标 Rust is_probably_encrypted_docx）
│   └── numberQa.ts              # 数字 QA（已有逻辑，提取为独立模块）
└── types/
    └── http.ts                  # 类型定义（已有）
```

### 2.2 Rust → Node.js 迁移对应表

| Rust 模块/函数 | Node.js 新模块 | 核心改动点 |
|---------------|---------------|-----------|
| `translation.rs` → `extract_word_segments()` | `services/docxParser.ts` | 用 `fast-xml-parser` SAX 模式重写，保留 Run 级格式提取 |
| `translation.rs` → `parse_inline_format_markers()` | `services/docxExporter.ts` | 将 `**bold**` 解析为格式结构，用于写回 XML |
| `translation.rs` → `patch_docx_translations()` | `services/docxExporter.ts` | JSZip 读写 + XML 重建，保留原始结构 |
| `translation.rs` → `translate_batch()` | `services/translation.ts` | `Promise.all` 分块并发，每块 25 段 |
| `translation.rs` → `check_number_consistency()` | `services/numberQa.ts` | 纯正则，逻辑等效 |
| `lib.rs` → pandoc 调用 + Lua 过滤器 | `services/pandoc.ts` | spawn pandoc + 动态生成 .lua 文件 |
| `lib.rs` → `is_probably_encrypted_docx()` | `services/docxSecurity.ts` | 读前 8 字节匹配 CFBF 魔数 |
| `lib.rs` → 锚点/书签处理 | `services/pandoc.ts` | Markdown 预处理 + XML 后处理 |
| `lib.rs` → 页码范围过滤 | `services/pandoc.ts` | 复用 `lastRenderedPageBreak` 解析逻辑 |
| `translation_memory.rs` | `services/tm.ts` + `routes/tm.ts` | SQLite TM 表，SHA-256 精确匹配 |
| `auth.rs` | `middleware.ts` | 已有 JWT 解析，Web 端由前端处理 PKCE |
| `settings.rs` | `routes/settings.ts` | 简单的 key-value 配置存 SQLite |

---

## 三、数据库表结构（需新增/补充）

在现有 `database.ts` 的 `migrate()` 中追加：

```sql
-- 翻译记忆库（对标 Rust translation_memory.db）
CREATE TABLE IF NOT EXISTS translation_memory (
  id TEXT PRIMARY KEY,
  source_lang TEXT NOT NULL,
  target_lang TEXT NOT NULL,
  source_hash TEXT NOT NULL,       -- SHA-256(source_text.trim())
  source_text TEXT NOT NULL,
  target_text TEXT NOT NULL,
  quality INTEGER NOT NULL DEFAULT 100,  -- 匹配质量（100=精确）
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tm_lookup
  ON translation_memory(source_lang, target_lang, source_hash);

-- 用户设置（对标 Rust settings.json）
CREATE TABLE IF NOT EXISTS user_settings (
  user_id TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, key)
);

-- 翻译任务段落快照（支持断点恢复 BR-01）
CREATE TABLE IF NOT EXISTS job_segments (
  job_id TEXT NOT NULL,
  segment_id TEXT NOT NULL,
  segment_order INTEGER NOT NULL,
  source_text TEXT NOT NULL,
  draft_translation TEXT,
  status TEXT NOT NULL DEFAULT 'pending',  -- pending / translated / reviewed
  qa_pass INTEGER DEFAULT 1,
  qa_reason TEXT,
  from_cache INTEGER DEFAULT 0,
  tm_quality INTEGER DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (job_id, segment_id)
);
```

---

## 四、关键服务实现思路

### 4.1 DOCX 解析器（docxParser.ts）— 对标 Rust `extract_word_segments`

**核心逻辑（从 Rust SAX 翻译）：**

```typescript
// 使用 fast-xml-parser 的 SAX 模式（或用 saxes 库）
// 关键行为：
// 1. 遇到 <w:p> 开始段落收集
// 2. 读 <w:pStyle w:val="xxx"> 获取 styleName
// 3. 遇到 <w:r> 开始 Run 收集
// 4. 在 <w:rPr> 中检测 <w:b/> / <w:i/> / <w:strike/>
// 5. 读 <w:t> 中的文本，拼接为 marked_text：
//    - bold → **text**, italic → *text*, strike → ~~text~~
// 6. 段落结束时：
//    - 跳过空段落
//    - 跳过代码样式（SourceCode/Verbatim/Pre）
//    - 输出 { id, order, sourceText(marked), plainText(stripped), styleName }
// 7. 特殊处理 <w:txbxContent> 内的段落（独立收集）
```

### 4.2 DOCX 导出器（docxExporter.ts）— 对标 Rust `patch_docx_translations`

**核心逻辑：**

```typescript
// 1. 构建 Map<plainText, translation>
//    plainText = stripInlineMarkers(sourceText)
// 2. SAX 遍历 word/document.xml：
//    - 对每个 <w:p>，收集段落纯文本
//    - 查 Map 命中 → 用译文替换
//    - 替换策略：
//      a. 解析译文中的 **bold** 标记
//      b. 为每个格式片段生成独立 <w:r>：
//         <w:r><w:rPr><w:b/></w:rPr><w:t>粗体文字</w:t></w:r>
//      c. 替换段落内所有原始 <w:r> 为新生成的 Run 序列
//    - 保留 <w:pPr>（段落属性）不变
// 3. JSZip 重打包
```

### 4.3 翻译分块并发（translation.ts 改造）

```typescript
const BATCH_SIZE = 25;

async function translateSegments(segments, opts) {
  const chunks = chunkArray(segments, BATCH_SIZE);
  const results = await Promise.all(
    chunks.map(chunk => callLambdaBatch(chunk, opts))
  );
  return results.flat();
}

async function callLambdaBatch(chunk, opts) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 90_000);
  try {
    // 带重试的 fetch
    return await fetchWithRetry(url, { signal: controller.signal, ... }, 3);
  } finally {
    clearTimeout(timer);
  }
}
```

### 4.4 进度推送（SSE）

```typescript
// routes/translation.ts
router.get("/jobs/:jobId/progress", (req, res) => {
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");
  
  const interval = setInterval(() => {
    const job = getJob(req.params.jobId);
    res.write(`data: ${JSON.stringify({ progress: job.progress, status: job.status })}\n\n`);
    if (job.status !== "running" && job.status !== "queued") {
      clearInterval(interval);
      res.end();
    }
  }, 1000);
  
  req.on("close", () => clearInterval(interval));
});
```

### 4.5 pandoc 增强（Lua 过滤器 + 模板 + 页码）

```typescript
async function convertMdToDocx(opts: {
  inputPath: string;
  outputPath: string;
  templatePath?: string;       // --reference-doc
  headingMappings?: HeadingMapping[];  // → 动态 Lua 过滤器
  anchorBookmarks?: boolean;   // 锚点→书签
}) {
  const args = [opts.inputPath, "-o", opts.outputPath];
  
  if (opts.templatePath) {
    args.push("--reference-doc", opts.templatePath);
  }
  
  if (opts.headingMappings?.length) {
    const luaContent = buildStyleMappingFilter(opts.headingMappings);
    const luaPath = path.join(tmpDir, "filter.lua");
    fs.writeFileSync(luaPath, luaContent);
    args.push("--lua-filter", luaPath);
  }
  
  await runPandoc(args, workDir);
  
  if (opts.anchorBookmarks) {
    await patchDocxBookmarks(opts.outputPath, anchorHeadings);
  }
}
```

### 4.6 翻译记忆库（tm.ts）

```typescript
import crypto from "node:crypto";

function hashText(text: string) {
  return crypto.createHash("sha256").update(text.trim()).digest("hex");
}

// 查找精确匹配
function lookupTm(sourceLang: string, targetLang: string, sourceText: string) {
  const hash = hashText(sourceText);
  return getDb()
    .prepare("SELECT target_text, quality FROM translation_memory WHERE source_lang = ? AND target_lang = ? AND source_hash = ?")
    .get(sourceLang, targetLang, hash);
}

// 翻译后写入 TM
function upsertTm(sourceLang: string, targetLang: string, sourceText: string, targetText: string, userId: string) {
  const hash = hashText(sourceText);
  const now = nowIso();
  getDb()
    .prepare(`INSERT INTO translation_memory (id, source_lang, target_lang, source_hash, source_text, target_text, quality, created_by, created_at, updated_at)
              VALUES (?, ?, ?, ?, ?, ?, 100, ?, ?, ?)
              ON CONFLICT(source_lang, target_lang, source_hash)
              DO UPDATE SET target_text = excluded.target_text, quality = 100, updated_at = excluded.updated_at`)
    .run(nanoid(), sourceLang, targetLang, hash, sourceText.trim(), targetText, userId, now, now);
}
```

---

## 五、前端 API 层规划（next-react-app 侧）

在 `src/api/` 目录下建立 API 封装：

```
src/api/
├── client.ts          # axios/fetch 基础封装，含 token 拦截器
├── convert.ts         # 格式转换 API
├── translation.ts     # 翻译 API（含 SSE 进度监听）
├── glossary.ts        # 术语表 CRUD
├── templates.ts       # 模板管理
├── reviews.ts         # 审校记录
├── tm.ts              # 翻译记忆
└── settings.ts        # 用户设置
```

### 前端关键对接点

| 页面 | 调用的后端 API | 交互模式 |
|------|-------------|---------|
| Convert | `POST /api/convert/jobs` → 轮询/SSE | 上传文件→创建 Job→获取结果→下载 |
| Translate | `POST /api/translation/jobs` → SSE 进度 | 上传→创建翻译 Job→实时进度→审校 |
| Reviews | `GET /api/reviews` + `PATCH` + `POST export` | 列表→详情编辑→导出 |
| Templates | `GET/POST/DELETE /api/templates` | 列表→上传→下载→删除 |
| Memory | `GET/POST/PATCH/DELETE /api/glossary` | 术语 CRUD + 导入 |
| Settings | `GET/PUT /api/settings` | 读取/保存配置 |

---

## 六、存储策略（单服务器本地优先）

| 数据类型 | Tauri 版存储 | Web 版存储 | 位置 |
|---------|-------------|-----------|------|
| 术语表 | DynamoDB + 本地 JSON 兜底 | **本地 SQLite** | `data/db/voltdocs.db` |
| 翻译记忆 | 本地 SQLite | **本地 SQLite** | 同上 |
| 模板文件 | S3 + 预签名 URL | **本地文件系统** | `data/templates/` |
| 上传文件 | 内存 bytes / 磁盘 | **本地文件系统** | `data/uploads/` |
| 翻译输出 | 磁盘直接写 | **本地文件系统** | `data/outputs/` |
| 审校记录 | localStorage + IndexedDB | **SQLite** | `review_records` + `job_segments` 表 |
| Job 状态 | 无（Tauri 同步调用） | **SQLite `jobs` 表** | 已有 |
| 用户设置 | 磁盘 JSON | **SQLite `user_settings` 表** | 新增 |
| JWT Token | 前端 localStorage | **前端 localStorage** | 浏览器侧 |

### 数据目录结构

```
/opt/voltdocs/data/          (Docker volume 挂载)
├── db/
│   └── voltdocs.db          # SQLite 主数据库
├── uploads/                  # 用户上传的原始文件
├── outputs/                  # 转换/翻译产出文件
├── templates/                # Word 模板文件
├── jobs/                     # Job 工作目录（临时）
└── archives/                 # 审校归档
```

---

## 七、API 接口设计（完整）

### 7.1 格式转换

```
POST   /api/convert/jobs              上传文件 + 转换参数 → 创建 Job
GET    /api/convert/jobs              列出转换任务
GET    /api/convert/jobs/:id          获取任务状态
GET    /api/convert/jobs/:id/progress SSE 进度流
DELETE /api/convert/jobs/:id          取消任务
```

请求体（multipart）：
- `file`: 上传文件
- `outputFormat`: `"md"` | `"docx"`
- `templateId?`: 使用的模板 ID
- `headingMappings?`: JSON 样式映射
- `pageRange?`: `"1-3,5"` 页码范围
- `pageMode?`: `"include"` | `"exclude"`
- `anchorBookmarks?`: `true/false`
- `postTranslate?`: `{ targetLang: "zh-CN" }`

### 7.2 翻译

```
POST   /api/translation/jobs              上传 DOCX + 语言对 → 创建翻译 Job
GET    /api/translation/jobs              列出翻译任务
GET    /api/translation/jobs/:id          获取任务详情（含段落结果）
GET    /api/translation/jobs/:id/progress SSE 进度流
PATCH  /api/translation/jobs/:id/segments 更新段落译文（审校编辑）
POST   /api/translation/jobs/:id/export   导出翻译后的 DOCX
POST   /api/translation/jobs/:id/confirm  批量确认段落 → 写入 TM
```

### 7.3 术语表

```
GET    /api/glossary                     查询术语（支持 sourceLang/targetLang/q 筛选）
POST   /api/glossary/terms               新增术语
PATCH  /api/glossary/terms/:id           更新术语
DELETE /api/glossary/terms/:id           删除术语
POST   /api/glossary/import/preview      CSV 导入预览
POST   /api/glossary/import/commit       确认导入
GET    /api/glossary/audit-logs          变更审计日志
```

### 7.4 模板

```
GET    /api/templates                    列出所有模板
POST   /api/templates                    上传模板（multipart）
PATCH  /api/templates/:id                更新标签/语言
DELETE /api/templates/:id                删除模板
GET    /api/files/:fileId/download       下载模板文件
```

### 7.5 翻译记忆

```
GET    /api/tm                           查询 TM 条目（分页）
GET    /api/tm/stats                     TM 统计（总量/命中率/节省 token）
POST   /api/tm/entries                   手动添加 TM 条目
DELETE /api/tm/entries/:id               删除条目
POST   /api/tm/import                    批量导入
```

### 7.6 审校

```
GET    /api/reviews                      列出审校记录
GET    /api/reviews/:id                  获取审校详情（含段落）
PATCH  /api/reviews/:id/segments/:segId  更新单段译文
POST   /api/reviews/:id/confirm          批量确认
POST   /api/reviews/:id/export           导出 DOCX
POST   /api/reviews/:id/archive          归档到本地
```

### 7.7 设置

```
GET    /api/settings                     获取当前用户全部设置
PUT    /api/settings                     批量更新设置
```

### 7.8 文件

```
GET    /api/files/:id/download           通用文件下载
```

---

## 八、实施分期

### Phase 1：基础能力贯通（2 周）

**目标**：翻译核心链路跑通（上传→解析→翻译→审校→导出）

| 任务 | 工作量 | 说明 |
|------|--------|------|
| 实现 `docxParser.ts` | 3 天 | SAX 解析，格式标记提取，文本框处理 |
| 改造 `translation.ts` 分块并发 | 1 天 | 25 段/块，Promise.all，超时重试 |
| 实现 `docxExporter.ts` | 2 天 | 格式标记还原，XML Run 重建 |
| 实现 SSE 进度推送 | 0.5 天 | 翻译 Job 进度实时推送 |
| 补 `job_segments` 表 | 0.5 天 | 段落级持久化，断点恢复基础 |
| 前端对接翻译流程 | 2 天 | API 层 + Translate 页面 + Reviews 页面 |
| 前端对接术语表 | 1 天 | Memory 页面 CRUD 对接 |

### Phase 2：格式转换增强（1 周）

| 任务 | 工作量 | 说明 |
|------|--------|------|
| pandoc Lua 过滤器生成 | 1 天 | 动态样式映射 |
| `--reference-doc` 模板支持 | 0.5 天 | 转换时注入选择的模板 |
| 锚点→书签后处理 | 1 天 | MD 预处理 + XML 书签注入 |
| 页码范围过滤 | 1 天 | 解析 lastRenderedPageBreak |
| 加密检测 + 友好提示 | 0.5 天 | CFBF 魔数检测 |
| 前端对接 Convert 页面 | 1 天 | 全部选项串通 |

### Phase 3：体验完善（1 周）

| 任务 | 工作量 | 说明 |
|------|--------|------|
| 翻译记忆库服务 | 1 天 | 查找/写入/统计 |
| TM 预查翻译（命中直接跳过 AI） | 1 天 | 翻译前先查 TM |
| 审校→TM 回写 | 0.5 天 | 确认段落后写入 TM |
| 模板管理前端对接 | 1 天 | Templates 页面 |
| Dashboard 统计数据 | 1 天 | 从 jobs/tm 表聚合 |
| 设置页面 | 0.5 天 | API 地址等配置 |

---

## 九、与 Lambda 的关系

当前保留调用现有 Lambda 的方式不变（已部署、已鉴权、Bedrock 权限已配置）。后续可选择：

**方案 A（推荐短期）**：继续调 Lambda
- 优点：零改动，Lambda 有 Bedrock 调用权限和重试逻辑
- 缺点：多一跳网络延迟

**方案 B（可选长期）**：后端直连 Bedrock SDK
- 优点：减少一跳延迟，不依赖 Lambda 冷启动
- 缺点：需要在服务器上配置 AWS credentials
- 实现：`@aws-sdk/client-bedrock-runtime`，invoke 与 Lambda 中的逻辑等效

两种方案在 `services/translation.ts` 中通过配置切换，接口不变。

---

## 十、Docker Compose 部署（不变）

现有 `docker-compose.yml` 结构不变，只需确保：
1. api 容器内安装了 pandoc（已有）
2. 数据卷 `/opt/voltdocs/data` 已挂载（已有）
3. 环境变量 `TRANSLATION_LAMBDA_URL` 指向 Lambda API Gateway（已有）

前端打包为静态文件，由 nginx 容器或 api 容器直接 serve。

---

*本文档为重构方向指引，具体代码实现将在后续开发中逐步完成。*
