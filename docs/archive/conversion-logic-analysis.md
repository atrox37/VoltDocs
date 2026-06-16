# VoltDocs 转换逻辑分析文档

> 分析日期：2026-06-04  
> 对比版本：Tauri 桌面端（DocumentConversionTool）→ Web 端（VoltDocs）

---

## 一、总体架构迁移对比

| 维度 | Tauri 桌面端 | VoltDocs Web 端（现状） |
|------|-------------|----------------------|
| 运行环境 | Windows 桌面，Rust 进程 | Docker 容器，Node.js Express |
| DOCX 解析 | Rust `quick-xml` + `zip` 库，精细 XML 操控 | TypeScript `JSZip` + 正则匹配，粗粒度 |
| 格式转换 | 内嵌 `pandoc.exe`，Tauri IPC 调用 | 系统 `pandoc`，`spawn` 子进程调用 |
| 翻译调用 | Rust 多线程并发，块大小 25 段 | Node.js `fetch` 单次调用，无分块 |
| 进度推送 | Tauri Event（`translation_progress`） | HTTP 轮询 Job 状态 |
| 文件持久化 | 前端 IndexedDB（原始 bytes）+ 磁盘 | 服务器本地文件系统（`data/uploads/`） |
| 认证 | Cognito PKCE，Rust TCP 回调，本地 token | JWT 透传（从前端 Header 转发给 Lambda） |
| 术语表 | 本地 `glossary.json` 兜底 + DynamoDB 主版本 | 本地 SQLite `glossary_terms` 表 |

---

## 二、文档翻译流程详细对比

### 2.1 Tauri 桌面端完整流程

```
用户拖入 .docx
      │
      ▼  [前端 JS] 读文件 bytes → 发 IPC: invoke("prepare_word_translation")
      │
      ▼  [Rust translation.rs] extract_word_segments()
        1. JSZip 解压 → 读 word/document.xml
        2. quick-xml SAX 解析，逐 <w:p> 段落遍历：
           · 提取 <w:pStyle> 取得 styleName
           · 跳过代码样式段落（SourceCode/Verbatim/Pre...）
           · 逐 <w:r> Run 级别收集文本：
             - 检测 <w:b>/<w:i>/<w:strike>，生成 **bold**/*italic*/~~strike~~ 占位符
             - 区分 plain_text（查找键）和 marked_text（发给 AI）
           · 文本框（<w:txbxContent>）内段落独立收集，作为普通段落追加
        3. 返回 WordTranslationSegment[] (id, order, sourceText=marked_text, ...)
      │
      ▼  [Rust] translate_batch()
        - 分块（每块 25 段），各块并发 spawn 独立线程
        - 每块：POST /translate/batch（JWT Bearer）→ Lambda
        - 线程汇聚，按 id 重新排列
        - 本地数字一致性 QA（extract_numbers 比对）
        - 返回含 qaPass/qaReason 的段落列表
      │
      ▼  [前端] 有 QA 问题 → 存 localStorage + IndexedDB → 跳审校页
          无 QA 问题 → invoke("save_result_file") → 写磁盘
      │
      ▼  [审校后] invoke("export_word_translation")
         [Rust] patch_docx_translations()
           - 用 strip_inline_bold_markers 从 sourceText 构建 plain_key
           - 构建 HashMap<plain_key, translation>
           - SAX 重写 word/document.xml：
             · 逐段落匹配 plain_text → 替换第一个 <w:t> 为译文，清空后续 <w:t>
             · 处理文本框内段落（translate_txbx_events）
             · 还原 **bold** 等占位符为 <w:b>/<w:i>/<w:strike> XML 标签
           - ZIP 重打包，写回 .docx
```

### 2.2 VoltDocs Web 端现状流程

```
用户上传 .docx
      │
      ▼  [前端] multipart/form-data POST /api/translation/jobs
         (携带 sourceLang/targetLang/Authorization Header)
      │
      ▼  [Express 路由] translation.ts
        - multer 存文件 → data/uploads/
        - registerFile() 写 SQLite files 表
        - createJob() 写 jobs 表，status='queued'
        - queueMicrotask → runWorker()
        - 立即返回 202 + job 对象
      │
      ▼  [Worker] runTranslationJob()
        - 更新进度 15%
        - extractDocxSegments()：
            · JSZip 读 word/document.xml
            · 正则匹配 /<w:p[\s\S]*?<\/w:p>/g
            · 对每个段落正则 /<w:t[^>]*>([\s\S]*?)<\/w:t>/g 拼接文本
            · 无样式检测，无格式标记提取（内联粗体/斜体会丢失）
        - 更新进度 35%
        - matchGlossaryTerms()：从本地 SQLite 匹配相关术语
        - translateSegments() → callTranslationLambda()：
            · 单次 fetch POST Lambda（无分块并发）
            · 本地数字 QA（numberQa，与 Rust 版逻辑等效）
        - 更新状态 succeeded，result_json 存段落列表
      │
      ▼  [前端轮询] GET /api/translation/jobs/:id
         获取到 succeeded 后展示段落 → 用户审校
      │
      ▼  [导出] POST /api/translation/jobs/:id/export
         [服务端] exportDocx()：
           - 正则替换每个 <w:p> 块内的 <w:t>
           - 第一个 <w:t> 写入译文，后续 <w:t> 清空
           - JSZip 重打包，写 data/outputs/
           - registerFile 注册 → 返回 downloadUrl
      │
      ▼  [前端] GET /api/files/:id/download → 浏览器下载
```

---

## 三、格式转换流程对比（md ↔ docx）

### 3.1 Tauri 版（Rust lib.rs）

核心能力清单：

| 功能 | 实现方式 |
|------|---------|
| md → docx | pandoc + `--reference-doc` 模板 + 动态 Lua 过滤器 |
| docx → md | pandoc + 页码范围过滤（解析 `<w:lastRenderedPageBreak>`） |
| 样式映射 | 动态生成 Lua 脚本，h1-h6/p/blockquote → Word 自定义样式 |
| HTML 锚点 → Word 书签 | 预处理 MD，将 `<a id="x">` 注入标题 `{#x}`，再用 SAX 在 XML 中插入 `<w:bookmarkStart>` |
| 加密检测 | 读前 8 字节匹配 CFBF 魔数 (`D0 CF 11 E0...`) |
| 大文件优化 | 输出直接写磁盘，不走 IPC bytes 回传 |
| pandoc 定位 | 多候选路径查找内嵌 pandoc.exe |

### 3.2 VoltDocs Web 版（jobs.ts → pandoc.ts）

```typescript
// jobs.ts - runConvertJob
await runPandoc([inputPath, "-o", outputPath], workDir);
// 等价于：pandoc <input> -o <output>，无任何额外选项
```

当前 Web 版调用非常简单，缺失：
- `--reference-doc` 模板支持
- Lua 过滤器 / 样式映射
- 页码范围过滤
- HTML 锚点 → 书签转换
- 加密检测（只检测 DOCX，Web 端无对应逻辑）

---

## 四、关键差异与迁移 Gap 分析

### 4.1 DOCX 解析质量差距（⚠️ 最严重）

| 问题 | Tauri 版 | Web 版现状 |
|------|---------|-----------|
| 格式标记保留 | 提取 Run 级 `<w:b>/<w:i>/<w:strike>`，转为 `**text**` 发给 AI | ❌ 无，所有格式标记丢失 |
| 代码段跳过 | 检测 `SourceCode/Verbatim` 样式，不翻译 | ❌ 无，代码也被翻译 |
| 文本框处理 | 独立解析 `<w:txbxContent>` 内段落 | ❌ 无，文本框内容丢失 |
| 样式名获取 | 读 `<w:pStyle w:val="">` 做类型分类 | ❌ 无样式感知 |
| 段落匹配键 | `plain_text`（剥离格式标记后的纯文本）| 直接用 `sourceText` |

**风险**：Web 版导出的 DOCX 中，所有原文的粗体/斜体/删除线均会丢失，代码块会被错误翻译。

### 4.2 翻译并发能力差距

| 维度 | Tauri 版 | Web 版现状 |
|------|---------|-----------|
| 分块策略 | 25 段/块，多块并行线程 | 单次请求，无分块 |
| 超时设置 | 90s per request | Node.js `fetch` 默认无超时 |
| 重试机制 | Lambda 侧 3 次指数退避 | 无客户端重试 |
| 进度反馈 | 实时 Tauri Event（原子计数器） | 轮询（进度仅 15% → 35% → 100% 三段） |

**风险**：长文档（>100 段）在 Web 版会单次发出超大请求，Lambda 29s 超时风险极高，且无降级重试。

### 4.3 导出重写策略差距（⚠️ 次严重）

| 维度 | Tauri 版 | Web 版现状 |
|------|---------|-----------|
| 替换粒度 | SAX 事件级，保留段落内所有 XML 结构（样式、边框、属性等）| 正则整段替换，第一个 `<w:t>` 写入，其余清空 |
| 格式还原 | `**bold**` → `<w:b>` XML 标签重建 | ❌ 无，即使 AI 返回了 `**text**` 也原样写入 |
| 文本框 | 独立处理 `txbxContent` | ❌ 文本框内容不写回 |
| 多 Run 段落 | 每个 Run 独立写译文片段 | 只有第一个 `<w:t>` 有内容，其余清空——段落内 Run 结构被破坏 |

**风险**：对于包含多个 Run（不同字体/颜色/超链接）的段落，Web 版会只保留第一个 Run 的文字，其余 Run 的文本清空，可能导致超链接文字消失、颜色变化丢失。

### 4.4 格式转换能力差距

Web 版当前是最简 pandoc 调用，缺少：
- **模板文档**（`--reference-doc`）：导出 DOCX 无法继承公司样式表
- **样式映射 Lua 过滤器**：Markdown 标题无法映射到 Word 自定义样式（如"标题 1"等中文样式名）
- **页码范围提取**：无法从大文档中提取指定页的内容
- **锚点书签**：MD 中的 `<a id="x">` 在转 DOCX 后无法生成可跳转书签

---

## 五、术语表架构对比

| 维度 | Tauri 版 | VoltDocs Web 版 |
|------|---------|----------------|
| 主存储 | AWS DynamoDB（`voltdocs-glossary`） | 本地 SQLite（`glossary_terms` 表） |
| 兜底方案 | 本地 `glossary.json`（90+ 条） | 无（SQLite 即主存储） |
| 字段 | `zh/en/context/enabled/required/forbidden` | `source_lang/target_lang/source_term/target_term/domain/context/required/enabled/priority` |
| 注入时机 | Lambda 侧（从 DynamoDB 缓存注入提示词） | Node.js 侧（matchGlossaryTerms 预匹配后随请求发给 Lambda） |
| 匹配策略 | Lambda 直接全量扫表 | 本地先过滤相关术语（ASCII 词边界/CJK 包含匹配），按 required/priority/length 排序，限制 chars 上限 |
| 多语言 | 只有 `zh/en` 两列（BR-07 日语扩展是待办）| 已有 `source_lang/target_lang` 字段，天然支持多语言对 |

Web 版术语表架构更灵活，多语言支持更好，本地匹配逻辑也比 Tauri 版精细（有优先级/字符上限控制）。

---

## 六、认证机制对比

| 维度 | Tauri 版 | VoltDocs Web 版 |
|------|---------|----------------|
| 认证方案 | Cognito PKCE，Rust TCP 回调（localhost:19991） | JWT 透传（前端携带 token 传给后端，后端转发给 Lambda） |
| Token 存储 | 磁盘文件（`%LOCALAPPDATA%/.../tokens.json`），不过 WebView | 前端持有（浏览器存储），后端无状态 |
| 自动续期 | Rust 侧检测过期后用 refresh_token 自动换新 token | 无（前端需自行处理） |
| 后端鉴权 | `requireAuth` 环境变量控制（开发可关闭）| 同左，`config.requireAuth` |

---

## 七、优先级迁移建议

基于差距分析，建议按以下优先级补齐：

### P0 — 核心功能正确性（影响输出质量）

**1. 升级 DOCX 解析器（extractDocxSegments）**

从正则匹配升级为 XML SAX 解析，需实现：
- Run 级别格式标记提取（`**bold**`/`*italic*`/`~~strike~~`）
- 代码样式段落跳过（`SourceCode/Verbatim`）
- 文本框段落（`<w:txbxContent>`）独立收集
- 样式名（`<w:pStyle>`）提取用于类型分类

建议参考 Tauri 版 `extract_word_segments` 逻辑，Node.js 可用 `sax` 或 `fast-xml-parser` 库实现等效 SAX 解析。

**2. 升级 DOCX 导出器（exportDocx）**

从正则替换升级为 XML 重写，需实现：
- 保留段落内原始 XML Run 结构，只替换文本内容
- `**bold**` 占位符还原为 `<w:b>`/`<w:i>`/`<w:strike>` XML 标签
- 文本框段落写回

**3. 翻译请求分块并发**

将 `translateSegments` 改为分批（建议 25 段/批）并发 `Promise.all`，并加上请求超时（90s）和 3 次重试。

### P1 — 转换功能完整性

**4. 格式转换补齐 pandoc 选项**

- 支持传入 `--reference-doc` 模板路径
- 支持 Lua 过滤器（样式映射）
- 加密 DOCX 检测（读前 8 字节匹配 CFBF 魔数）

**5. 进度反馈细化**

当前仅有 3 个进度节点（15/35/100），建议每个翻译批次完成后更新进度（类似 Tauri 原子计数器方案，Web 版可用 SSE 或 WebSocket 替代 Tauri Event）。

### P2 — 体验与可靠性

**6. 翻译任务断点恢复（BR-01）**

当前 Job 数据已存 SQLite，基础设施已具备，需要：
- 前端展示"可恢复"任务
- 恢复时从已完成段落位置继续，不重新翻译已完成部分

**7. 加密文档友好提示（BR-04）**

检测到加密 DOCX 后显示模态引导弹窗，而非通用错误。

---

## 八、Web 版现有优势（保留/借鉴）

1. **术语表多语言架构**：`source_lang/target_lang` 字段设计天然支持 BR-07 日语扩展，比 Tauri 版更优
2. **术语匹配精细度**：本地预匹配 + 优先级排序 + chars 上限，比 Lambda 侧全量注入更可控
3. **Job 队列模式**：异步 Job 模式天然支持断点恢复、进度轮询，基础设施比 Tauri 实时模式更适合 Web
4. **文件注册表**：`files` 表统一管理所有输入输出文件，便于清理和追踪
5. **Docker 化部署**：多人共用，无需每台电脑安装 Tauri 环境

---

## 九、文件对应关系速查

| 功能 | Tauri 版文件 | VoltDocs Web 版文件 |
|------|-------------|-------------------|
| DOCX 段落提取 | `src-tauri/src/translation.rs` → `extract_word_segments()` | `backend/src/services/translation.ts` → `extractDocxSegments()` |
| 翻译请求 | `translation.rs` → `translate_batch()` | `translation.ts` → `callTranslationLambda()` |
| DOCX 写回 | `translation.rs` → `patch_docx_translations()` | `translation.ts` → `exportDocx()` |
| 格式转换 | `src-tauri/src/lib.rs` → pandoc + Lua | `backend/src/services/pandoc.ts` + `services/jobs.ts` → `runConvertJob()` |
| Job 调度 | Tauri IPC 同步调用 | `backend/src/services/jobs.ts` → `runWorker()` |
| 术语匹配 | Lambda 侧 DynamoDB 缓存 | `backend/src/services/glossaryMatcher.ts` |
| 认证 | `src-tauri/src/auth.rs` | `backend/src/middleware.ts` |
| 数字 QA | `translation.rs` → `check_number_consistency()` | `translation.ts` → `numberQa()` |

---

*文档自动生成，基于对两个项目源码的静态分析。*
