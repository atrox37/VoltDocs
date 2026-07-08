# VoltDocs 技术架构文档

> **适合人群**：开发团队成员  
> **文档用途**：理解系统架构、二次开发、技术决策参考

---

# 第一部分：系统架构概览

## 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户浏览器                              │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP/HTTPS
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Nginx (Docker: web)                        │
│              端口: 8088 (HTTP) / 18088 (HTTPS)                  │
│   ├── 静态文件服务 (前端 build)                                  │
│   └── 反向代理 /api/* → api:8080                               │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI (Docker: api)                        │
│                      端口: 8080                                 │
├─────────────────────────────────────────────────────────────────┤
│  路由层 (routes/)                                               │
│  ├── translation.py    - 文档翻译                               │
│  ├── convert.py        - 文档转换                               │
│  ├── glossary.py       - 术语库管理                             │
│  ├── files.py          - 文件下载                               │
│  ├── templates.py      - 模板管理                               │
│  ├── users.py          - 用户管理                               │
│  └── health.py         - 健康检查                               │
├─────────────────────────────────────────────────────────────────┤
│  服务层 (services/)                                             │
│  ├── docx_parser.py / docx_exporter.py  - Word 处理            │
│  ├── excel_parser.py / excel_exporter.py - Excel 处理          │
│  ├── md_parser.py / md_exporter.py      - Markdown 处理        │
│  ├── translation.py    - 翻译编排                               │
│  ├── glossary_matcher.py - 术语匹配                            │
│  ├── tm.py             - 翻译记忆                               │
│  ├── qa_*.py           - 质量检查                               │
│  └── bedrock.py        - AWS Bedrock 集成                      │
├─────────────────────────────────────────────────────────────────┤
│  数据层                                                         │
│  ├── SQLite (WAL 模式)                                          │
│  └── 文件系统 (uploads/, outputs/, templates/)                 │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      AWS Bedrock (Nova)                         │
│              翻译模型: nova-lite-v1 / nova-micro-v1             │
└─────────────────────────────────────────────────────────────────┘
```

## 1.2 技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| 前端 | React + TypeScript + Ant Design + Vite | React 18, TS 5.x |
| 后端 | Python + FastAPI | Python 3.11, FastAPI 0.109+ |
| 数据库 | SQLite (WAL mode) | - |
| AI | AWS Bedrock (Nova) | nova-lite-v1:0 |
| Excel处理 | openpyxl | 3.1.x |
| Word处理 | lxml | 5.x |
| 部署 | Docker Compose + Nginx | - |

---

# 第二部分：核心模块详解

## 2.1 文档解析（Parser）

### Word 文档 (docx_parser.py)

**技术实现**：直接使用 `lxml` 解析 DOCX 的内部 XML 结构

**解析流程**：
```python
# 1. 打开 ZIP 文件（DOCX 本质是 ZIP）
with zipfile.ZipFile(BytesIO(content)) as archive:
    # 2. 读取主文档内容
    xml = archive.read("word/document.xml")
    # 3. 解析 XML
    root = etree.fromstring(xml)
    # 4. 遍历段落
    for paragraph in root.xpath(".//w:p"):
        ...
```

**处理的 XML 部件**：
- `word/document.xml` - 正文
- `word/header*.xml` - 页眉
- `word/footer*.xml` - 页脚

**片段提取**：
```python
{
    "id": "seg-1",
    "source_text": "**加粗文本**",  # 带格式标记
    "plain_text": "加粗文本",        # 纯文本
    "style_name": "Heading 1",      # 段落样式
    "segment_type": "title",        # 片段类型
    "_docx_location": {
        "part_name": "word/document.xml",
        "paragraph_index": 0
    }
}
```

**格式标记规则**：
- `**text**` → 加粗
- `*text*` → 斜体
- `~~text~~` → 删除线

### Excel 文档 (excel_parser.py)

**技术实现**：使用 `openpyxl` 库

**解析流程**：
```python
workbook = openpyxl.load_workbook(BytesIO(content))
for sheet in workbook.worksheets:
    # 1. 工作表标题
    if sheet.title.strip():
        segments.append({"segment_type": "sheet_title", ...})
    # 2. 单元格内容
    for row in sheet.iter_rows():
        for cell in row:
            if cell.value and isinstance(cell.value, str):
                segments.append({"segment_type": "cell", ...})
```

**片段结构**：
```python
{
    "id": "Sheet1_A1",
    "source_text": "逆变器",
    "style_name": "Sheet1",
    "segment_type": "cell",
    "sheet": "Sheet1",      # 工作表名
    "cell": "A1"            # 单元格坐标
}
```

**过滤规则**：使用正则 `[\W\d_]+` 过滤纯数字/符号内容

## 2.2 翻译编排 (translation.py)

### 核心流程

```
用户上传文件
    ↓
pick_parser(filename) → 确定文件类型和解析器
    ↓
parser(content) → 提取片段列表
    ↓
load_glossary_terms() → 加载术语表
    ↓
_split_into_batches() → 按类型分批
    ↓
translate_segments() → 并行翻译
    ├─ 检查翻译记忆 (TM)
    ├─ 调用 Bedrock API
    ├─ QA 检查
    └─ 存储到 TM
    ↓
export_*(原始文件, 片段, 翻译结果) → 生成输出
    ↓
返回文件ID
```

### 分批策略

**Excel 分批** (`_split_xlsx_batches`)：
- `passthrough`: 不需要翻译的内容
- `label`: 短标签（≤4词）
- `short_text`: 短文本（≤24字符）
- `long_text`: 长文本（≥40字符或≥8词）
- `content`: 普通内容

**Word 分批** (`_split_into_batches`)：
按片段类型和样式分组：
- `title`: 标题
- `table`: 表格内容
- `structured`: 列表/引用
- `label`: 短标签
- `paragraph`: 普通段落

### 批量限制

| 文件类型 | 最大字节 | 最大片段数 |
|---------|---------|-----------|
| .xlsx   | 5000    | 40        |
| .docx   | 2500    | 15        |
| .md     | 5000    | 40        |

## 2.3 术语表匹配 (glossary_matcher.py)

### 数据结构

```sql
CREATE TABLE glossary_terms (
    id TEXT PRIMARY KEY,
    source_lang TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    source_term TEXT NOT NULL,      -- 源语言术语
    target_term TEXT NOT NULL,      -- 目标语言术语
    context TEXT,                    -- 上下文/说明
    required INTEGER DEFAULT 0,      -- 是否强制使用
    enabled INTEGER DEFAULT 1,       -- 是否启用
    priority INTEGER DEFAULT 0,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### 匹配流程

1. **加载阶段**：`load_glossary_terms(db, source_lang, target_lang)`
2. **选择阶段**：`select_terms_for_texts()` - 选择当前批次涉及的术语
3. **应用阶段**：`terms_for_source()` - 为单个片段选择术语
4. **构建提示**：在 Prompt 中加入术语列表
   ```python
   f"- 逆变器 -> inverter [context: 光伏系统]"
   ```

### 双向使用

中译英和英译中共享同一术语表：
- 中→英：`source_term=中文, target_term=英文`
- 英→中：自动反转查找

## 2.4 翻译记忆 (tm.py)

### 用途

缓存历史翻译结果，加速重复内容翻译

### 数据结构

```sql
CREATE TABLE translation_memory (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL DEFAULT 'global',  -- global / filetype:xlsx / document:sha256
    source_lang TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    source_hash TEXT NOT NULL,              -- sha256(原文)
    source_text TEXT NOT NULL,
    target_text TEXT NOT NULL,
    quality INTEGER DEFAULT 100,
    hit_count INTEGER DEFAULT 0,
    last_hit_at TEXT,
    locked INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### 查询逻辑

```python
# 1. 构建查询范围（按优先级）
lookup_scopes = [
    f"document:{sha256}",   # 当前文档
    f"filetype:{file_type}", # 当前文件类型
    "global"                # 全局
]

# 2. 精确匹配
SELECT * FROM translation_memory
WHERE scope IN (?, ?, ?)
  AND source_lang = ?
  AND target_lang = ?
  AND source_hash = ?
  AND quality >= 80
ORDER BY scope, hit_count DESC
```

## 2.5 质量检查 (QA)

### 检查项目

| 检查项 | 说明 | 不通过处理 |
|-------|------|-----------|
| 译文非空 | 确保 AI 返回了翻译 | 标记 `qa_pass=0` |
| 数字一致 | 原文数字必须在译文中出现 | 标记 |
| 格式保留 | `**`, `*`, `~~` 必须保留 | 标记 |
| 长度合理 | 译文字数应在合理范围 | 标记 |
| 语言正确 | 译文应是目标语言 | 标记 |
| 术语一致 | 术语表术语必须使用 | 标记 |
| 标点规范 | 英文不能有中文标点 | 标记 |

### AI QA (可选)

当 `QA_AI_ENABLED=true` 时，会调用 Nova 模型对译文进行进一步评估

## 2.6 文档导出 (Exporter)

### Word 导出 (docx_exporter.py)

**复杂点**：需要保留所有格式，同时替换文本

**核心逻辑**：
```python
# 1. 解析格式标记
parts = _parse_inline_format_markers(translation)
# [("text", bold=True, italic=False, strike=False), ...]

# 2. 捕获原始 Run 模板（保留字体、颜色等）
templates = _capture_run_templates(paragraph)

# 3. 构建新内容
for text, bold, italic, strike in parts:
    new_run = _make_run(text, template, bold, italic, strike)
    paragraph.append(new_run)
```

**保留的内容**：
- 字体属性（字体名、大小、颜色）
- 加粗/斜体/下划线
- 图片和绘图
- 表格布局
- 字段代码

### Excel 导出 (excel_exporter.py)

**逻辑较简单**：
```python
workbook = openpyxl.load_workbook(BytesIO(original_bytes))
for parsed, request in zip(parsed_segments, request_segments):
    translation = request.get("draft_translation")
    sheet = workbook[parsed["sheet"]]
    if parsed["segment_type"] == "sheet_title":
        sheet.title = translation  # 重命名工作表
    else:
        sheet[parsed["cell"]] = translation  # 写入单元格
```

---

# 第三部分：API 设计

## 3.1 翻译 API

### 创建翻译任务
```http
POST /api/translation/jobs
Content-Type: multipart/form-data

file: <file>
sourceLang: zh-CN
targetLang: en-US
```

### 获取任务状态
```http
GET /api/translation/jobs/{job_id}
```

### 导出译文
```http
POST /api/translation/jobs/{job_id}/export
Content-Type: application/json

{
  "segments": [
    {"id": "seg-1", "translation": "translated text"}
  ]
}
```

## 3.2 术语库 API

```http
GET    /api/glossary/terms          # 列表
POST   /api/glossary/terms          # 添加
PUT    /api/glossary/terms/{id}     # 更新
DELETE /api/glossary/terms/{id}     # 删除
POST   /api/glossary/terms/import   # 批量导入
```

---

# 第四部分：扩展开发指南

## 4.1 添加新文件格式

假设要添加 PPTX 支持：

1. **创建解析器** `services/pptx_parser.py`
   ```python
   def extract_segments(content: bytes) -> list[dict]:
       # 解析 PPTX，提取文本
       return [{"id": "...", "source_text": "...", ...}]
   ```

2. **创建导出器** `services/pptx_exporter.py`
   ```python
   def export_pptx(original_bytes, parsed, translated) -> bytes:
       # 写入翻译结果
       return output_bytes
   ```

3. **注册格式** 在 `routes/translation.py` 中：
   ```python
   def _pick_parser(filename: str):
       if filename.endswith(".pptx"):
           return "pptx", extract_pptx_segments
   ```

4. **处理导出** 在翻译完成后的处理逻辑中添加 `.pptx` 分支

## 4.2 自定义 QA 规则

在 `services/qa_*.py` 中添加新的检查函数：

```python
def check_custom_rule(segment: dict, translation: str) -> tuple[bool, str]:
    # 自定义检查逻辑
    if "forbidden" in translation:
        return False, "Contains forbidden word"
    return True, ""
```

然后在 `evaluate_segments_qa_with_repair()` 中调用

## 4.3 添加新翻译后端

当前支持：
1. AWS Bedrock (默认)
2. 自定义 Lambda (通过 `TRANSLATION_LAMBDA_URL`)

如需添加其他翻译服务，修改 `services/bedrock.py` 或创建新模块

---

# 第五部分：配置参考

## 环境变量

| 变量 | 说明 | 示例值 |
|------|------|--------|
| `PORT` | 服务端口 | `8080` |
| `DATA_DIR` | 数据目录 | `/opt/voltdocs/data` |
| `REQUIRE_AUTH` | 是否启用认证 | `true` |
| `INITIAL_ADMIN_EMAIL` | 初始超级管理员 | `admin@example.com` |
| `BEDROCK_MODEL_ID` | 翻译模型 | `us.amazon.nova-lite-v1:0` |
| `BEDROCK_REGION` | AWS 区域 | `us-east-1` |
| `TRANSLATION_BATCH_MAX_BYTES` | 每批最大字节 | `5000` |
| `TRANSLATION_BATCH_MAX_SEGMENTS` | 每批最大片段 | `40` |
| `QA_AI_ENABLED` | 启用AI QA | `true` |
| `GLOSSARY_MAX_TERMS_PER_REQUEST` | 术语数量限制 | `100` |
| `COGNITO_DOMAIN` | Cognito 域名 | `xxx.auth.us-east-1.amazoncognito.com` |
| `COGNITO_CLIENT_ID` | 应用客户端ID | `2fnmsk89dt0066l...` |
| `COGNITO_REDIRECT_URI` | 回调地址 | `http://localhost:8080/api/auth/callback` |

---

*VoltDocs 技术文档 · Voltage Energy 内部使用*