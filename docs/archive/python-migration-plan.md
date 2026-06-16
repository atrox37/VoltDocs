# VoltDocs 后端迁移规划：Rust → Python

## 文档说明

本文档供 AI 辅助实现使用。描述现有 Rust 后端的完整逻辑，以及迁移到 Python（FastAPI）后端的目标架构、数据模型、接口契约和实现要求。

**迁移原则：**
- 前端代码（React + TypeScript）**不做任何修改**
- 所有 API 路径、请求/响应格式**完全保持不变**
- SQLite 数据库文件**直接复用**，表结构不变
- `.env` 环境变量名称**保持不变**

---

## 一、现有架构概览

### 技术栈（现有）

```
前端:  React + TypeScript + Ant Design (Vite, 端口 5173)
后端:  Rust + Actix-Web (端口 8080)
数据库: SQLite (./data/db/voltdocs.db)
认证:  AWS Cognito (User Pool: us-east-1_flUobqcda)
翻译:  AWS Lambda (https://znu9uvkvgk.execute-api.us-east-1.amazonaws.com/prod)
转换:  Pandoc (命令行工具)
```

### 目标技术栈（Python）

```
前端:  React + TypeScript + Ant Design (不变)
后端:  Python 3.11+ + FastAPI + uvicorn (端口 8080)
数据库: SQLite (aiosqlite + SQLAlchemy Core，文件路径不变)
认证:  AWS Cognito (逻辑不变)
翻译:  AWS Lambda (逻辑不变)
转换:  Pandoc (subprocess 调用，逻辑不变)
文件解析: python-docx / openpyxl / python-pptx
```

---

## 二、项目目录结构（目标）

```
d:\Project\VoltDocs\
├── backend-py/                    ← 新 Python 后端（替换 backend-rs/）
│   ├── main.py                    ← 入口，FastAPI app 创建
│   ├── config.py                  ← 从 .env 读取配置
│   ├── database.py                ← SQLite 连接和迁移
│   ├── requirements.txt           ← 依赖列表
│   ├── .env                       ← 环境变量（复制自 backend-rs/.env）
│   ├── auth/
│   │   ├── cognito.py             ← Cognito OAuth2 客户端
│   │   ├── middleware.py          ← FastAPI 认证中间件
│   │   ├── routes.py              ← /api/auth/* 路由
│   │   └── session.py             ← 内存 session store
│   ├── routes/
│   │   ├── convert.py             ← /api/convert/* 路由
│   │   ├── translation.py         ← /api/translation/* 路由
│   │   ├── glossary.py            ← /api/glossary/* 路由
│   │   ├── templates.py           ← /api/templates/* 路由
│   │   ├── files.py               ← /api/files/* 路由
│   │   ├── users.py               ← /api/users/* 路由
│   │   └── settings.py            ← /api/settings/* 路由
│   └── services/
│       ├── docx_parser.py         ← DOCX 段落提取（python-docx）
│       ├── docx_exporter.py       ← DOCX 译文写回（python-docx）
│       ├── excel_parser.py        ← Excel 单元格提取（openpyxl）
│       ├── excel_exporter.py      ← Excel 译文写回（openpyxl）
│       ├── pptx_parser.py         ← PPTX 文本提取（python-pptx）
│       ├── pptx_exporter.py       ← PPTX 译文写回（python-pptx）
│       ├── translation.py         ← 调用 Lambda 翻译服务
│       ├── pandoc.py              ← subprocess 调用 pandoc
│       ├── storage.py             ← 文件存储工具函数
│       └── glossary_matcher.py    ← 术语匹配逻辑
└── frontend/                      ← 不变
```

---

## 三、环境变量（.env）

与现有 `backend-rs/.env` **完全相同**，复制到 `backend-py/.env`：

```env
PORT=8080
DATA_DIR=./data
PANDOC_PATH=pandoc
PANDOC_TIMEOUT_SECONDS=300
MAX_UPLOAD_MB=50
TRANSLATION_LAMBDA_URL=https://znu9uvkvgk.execute-api.us-east-1.amazonaws.com/prod
TRANSLATION_BATCH_SEGMENTS=25
TRANSLATION_TIMEOUT_SECONDS=90
GLOSSARY_MAX_TERMS_PER_REQUEST=100
GLOSSARY_MAX_PROMPT_CHARS=12000
REQUIRE_AUTH=true
DEV_USER_EMAIL=dev@voltdocs.local
INITIAL_ADMIN_EMAIL=<填写>
COGNITO_DOMAIN=https://us-east-1fluobqcda.auth.us-east-1.amazoncognito.com
COGNITO_CLIENT_ID=2fnmsk89dt0066l25kmi68m7qp
COGNITO_CLIENT_SECRET=
COGNITO_REDIRECT_URI=http://localhost:8080/api/auth/callback
```

---

## 四、依赖库（requirements.txt）

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
python-dotenv==1.0.0
aiosqlite==0.20.0
httpx==0.27.0
python-multipart==0.0.9
python-docx==1.1.2
openpyxl==3.1.5
python-pptx==1.0.2
PyJWT==2.9.0
cryptography==43.0.0
uuid==1.30
```

---

## 五、数据库（database.py）

### SQLite 文件路径

```python
# config.py
DATA_DIR = os.getenv("DATA_DIR", "./data")
DB_PATH = os.path.join(DATA_DIR, "db", "voltdocs.db")
```

### 表结构（直接复用，不做修改）

以下所有表在 Python 版本中通过 `CREATE TABLE IF NOT EXISTS` 确保存在：

```sql
-- 文件记录
CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    original_name TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    mime_type TEXT,
    size INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT,
    created_at TEXT NOT NULL
);

-- 任务（翻译/转换）
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    input_file_id TEXT,
    output_file_id TEXT,
    payload_json TEXT,
    result_json TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

-- 翻译段落
CREATE TABLE IF NOT EXISTS job_segments (
    job_id TEXT NOT NULL,
    segment_id TEXT NOT NULL,
    segment_order INTEGER NOT NULL,
    source_text TEXT NOT NULL,
    draft_translation TEXT DEFAULT '',
    style_name TEXT,
    segment_type TEXT NOT NULL DEFAULT 'paragraph',
    status TEXT NOT NULL DEFAULT 'pending',
    qa_pass INTEGER DEFAULT 1,
    qa_reason TEXT,
    from_cache INTEGER DEFAULT 0,
    tm_quality INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (job_id, segment_id)
);

-- 模板
CREATE TABLE IF NOT EXISTS templates (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    language TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    uploaded_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 术语表
CREATE TABLE IF NOT EXISTS glossary_terms (
    id TEXT PRIMARY KEY,
    source_lang TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    source_term TEXT NOT NULL,
    target_term TEXT NOT NULL,
    domain TEXT,
    context TEXT,
    required INTEGER NOT NULL DEFAULT 0,
    forbidden_terms_json TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 术语操作日志
CREATE TABLE IF NOT EXISTS glossary_audit_logs (
    id TEXT PRIMARY KEY,
    term_id TEXT,
    action TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- 翻译记忆库
CREATE TABLE IF NOT EXISTS translation_memory (
    id TEXT PRIMARY KEY,
    source_lang TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    source_text TEXT NOT NULL,
    target_text TEXT NOT NULL,
    quality INTEGER NOT NULL DEFAULT 100,
    created_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 用户设置
CREATE TABLE IF NOT EXISTS user_settings (
    user_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

-- 用户角色（三级：super_admin / manager / user）
CREATE TABLE IF NOT EXISTS user_roles (
    email       TEXT PRIMARY KEY NOT NULL,
    role        TEXT NOT NULL DEFAULT 'user'
                CHECK(role IN ('super_admin','manager','user')),
    created_at  TEXT NOT NULL,
    last_login  TEXT
);

-- 角色变更审计
CREATE TABLE IF NOT EXISTS role_audit_log (
    id           TEXT PRIMARY KEY,
    actor_email  TEXT NOT NULL,
    target_email TEXT NOT NULL,
    old_role     TEXT NOT NULL,
    new_role     TEXT NOT NULL,
    changed_at   TEXT NOT NULL
);
```

### 启动时 seed

```python
# 如果 INITIAL_ADMIN_EMAIL 非空，在 user_roles 中插入 super_admin（INSERT OR IGNORE）
INSERT OR IGNORE INTO user_roles (email, role, created_at)
VALUES (?, 'super_admin', ?)
```

---

## 六、认证系统（auth/）

### 角色层级

```
super_admin > manager > user

super_admin: 用户管理 + 模板/术语修改 + 查看审计日志
manager:     模板/术语修改 + 查看审计日志
user:        使用翻译/转换功能，只读查看
```

### session.py

```python
# 内存 session store，用 dict + asyncio.Lock
# SessionData 结构：
{
    "session_id": str,
    "email": str,
    "name": str,
    "role": str,          # 'super_admin' | 'manager' | 'user'
    "created_at": datetime,
    "last_active": datetime,
    "access_token": str,  # Cognito access token，用于调用 Lambda
    "refresh_token": str  # Cognito refresh token
}

# 超时规则：
IDLE_TIMEOUT_MINUTES = 30
ABSOLUTE_TIMEOUT_HOURS = 8

# Cookie 名称：
SESSION_COOKIE = "voltdocs_session"
```

### cognito.py

```python
# Cognito 配置
USER_POOL_ID = "us-east-1_flUobqcda"
CLIENT_ID = "2fnmsk89dt0066l25kmi68m7qp"
REGION = "us-east-1"

# 授权 URL 构建（关键：必须包含 identity_provider 参数）
def authorization_url(state: str) -> str:
    return (
        f"{COGNITO_DOMAIN}/oauth2/authorize"
        f"?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={quote(REDIRECT_URI)}"
        f"&scope=openid%20email%20profile"
        f"&identity_provider=MicrosoftTeamsOIDC"  # ← 必须有此参数
        f"&state={state}"
    )

# Token 交换
# POST {COGNITO_DOMAIN}/oauth2/token
# body: grant_type=authorization_code, client_id, redirect_uri, code
# 无 client_secret（当前配置为空）

# JWT claims 提取（从 id_token 的 base64 payload 解析）
# 字段：email, name（用于显示名称）
```

### routes.py（auth 路由）

```
GET  /api/auth/login-url   → 返回 {"url": "<cognito授权URL>"}
GET  /api/auth/callback    → 交换 code，创建 session，设置 cookie，重定向到 /
POST /api/auth/logout      → 删除 session，清除 cookie
GET  /api/auth/me          → 返回当前用户信息或 401
```

**GET /api/auth/me 响应格式：**
```json
{"email": "user@example.com", "name": "张三", "role": "super_admin"}
```

**GET /api/auth/callback 流程：**
1. 用 code 向 Cognito `/oauth2/token` 换取 token_set
2. 从 id_token 的 JWT payload（base64 解码）提取 email 和 name
3. `INSERT OR IGNORE INTO user_roles` 插入新用户（默认 role='user'）
4. `UPDATE user_roles SET last_login` 更新登录时间
5. 查询用户 role
6. 创建 session（含 access_token），存入内存 store
7. Set-Cookie: voltdocs_session=<session_id>; HttpOnly; SameSite=Lax
8. 302 重定向到 /

**REQUIRE_AUTH=false 时的开发模式：**
- `GET /api/auth/me` 直接返回 `{"email": DEV_USER_EMAIL, "name": "Dev User", "role": "super_admin"}`
- 所有受保护路由注入 dev 用户，跳过 session 验证

### middleware.py

```python
# FastAPI Dependency，注入到所有受保护路由
async def get_current_user(request: Request) -> CurrentUser:
    if not REQUIRE_AUTH:
        return CurrentUser(email=DEV_USER_EMAIL, name="Dev User", role="super_admin")
    
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        raise HTTPException(401, "unauthenticated")
    
    session = session_store.get(session_id)
    if not session or is_expired(session):
        raise HTTPException(401, "unauthenticated")
    
    session["last_active"] = datetime.utcnow()
    return CurrentUser(**session)

# 权限检查函数
def require_min_role(user: CurrentUser, min_role: str):
    """角色层级: super_admin > manager > user"""
    hierarchy = {"super_admin": 0, "manager": 1, "user": 2}
    if hierarchy[user.role] > hierarchy[min_role]:
        raise HTTPException(403, "forbidden")
```

### 后台任务：session 清理

每 5 分钟清理一次过期 session（使用 `asyncio` background task 或 `apscheduler`）。

---

## 七、API 路由详细说明

### 7.1 转换任务（routes/convert.py）

```
POST /api/convert/jobs
  - 接收: multipart/form-data
    - file: 文件
    - outputFormat: "docx" | "md"
    - templateId: str（可选）
    - outputFileName: str（可选，用户指定输出文件名）
  - 权限: 所有已认证用户
  - 逻辑:
    1. 保存文件到 {DATA_DIR}/uploads/
    2. 插入 jobs 记录（status='queued'）
    3. 插入 glossary_audit_logs 记录（action='job_created'）
    4. 后台启动转换任务
  - 响应: {"id": "<job_id>", "status": "queued"}

GET /api/convert/jobs
  - 返回最近 50 条 type='convert' 的任务列表

GET /api/convert/jobs/{job_id}
  - 返回单个任务详情

GET /api/convert/jobs/{job_id}/progress
  - 返回 {"status": "...", "progress": 0-100}
```

**转换任务后台逻辑：**
```python
# 使用 asyncio.create_task 或 BackgroundTasks
# 调用 pandoc 命令行（subprocess）
# 关键：pandoc 的 cwd 必须设置为输入文件所在目录（uploads/）
# 关键：模板路径必须是绝对路径（os.path.abspath）
# 输出文件保存到 {DATA_DIR}/outputs/
```

**Pandoc 调用示例：**
```python
import subprocess, os

def run_pandoc(input_path: str, output_path: str, template_path: str = None,
               pandoc_bin: str = "pandoc", timeout: int = 300):
    args = [pandoc_bin, os.path.abspath(input_path),
            "-o", os.path.abspath(output_path)]
    if template_path:
        args += ["--reference-doc", os.path.abspath(template_path)]
    
    work_dir = os.path.dirname(os.path.abspath(input_path))  # ← cwd = 输入文件目录
    result = subprocess.run(args, cwd=work_dir, timeout=timeout,
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Pandoc failed (exit {result.returncode}): {result.stderr}")
```

### 7.2 翻译任务（routes/translation.py）

```
POST /api/translation/jobs
  - 接收: multipart/form-data
    - file: DOCX/Excel/PPTX 文件
    - sourceLang: str（如 "zh-CN"）
    - targetLang: str（如 "en-US"）
  - 权限: 所有已认证用户
  - 逻辑:
    1. 校验文件格式（DOCX 需检查是否加密）
    2. 保存文件到 uploads/
    3. 从 session 取 access_token 存入 payload_json（用于调用 Lambda）
    4. 插入 jobs 记录
    5. 后台启动翻译任务
  - 响应: {"id": "<job_id>", "status": "queued"}

GET /api/translation/jobs
GET /api/translation/jobs/{job_id}
GET /api/translation/jobs/{job_id}/progress

POST /api/translation/jobs/{job_id}/export
  - 接收: {"segments": [{"sourceText": "...", "translation": "..."}]}
  - 逻辑: 把审校后的译文写回原始文件格式并返回下载链接
  - 响应: {"fileId": "...", "fileName": "...", "downloadUrl": "..."}
```

**翻译任务后台逻辑：**
```python
# 1. 根据文件格式选择解析器
parser = DocxParser | ExcelParser | PptxParser

# 2. 提取段落
segments = parser.extract(file_bytes)
# 返回: [{"id": "seg-1", "text": "原文", "style": "Normal", ...}]

# 3. 从本地 SQLite 匹配术语表，构建 system_prompt
# （注意：Lambda 内部也会从 DynamoDB 加载术语表，
#  本地术语表是额外的，两者叠加使用）

# 4. 调用 Lambda（并行批次，每批 25 段）
# POST {TRANSLATION_LAMBDA_URL}/translate/batch
# Headers: Authorization: Bearer {access_token}
# Body: {"sourceLang": "zh-CN", "targetLang": "en-US",
#        "segments": [{"id": "seg-1", "text": "..."}]}
# 响应: {"segments": [{"id": "seg-1", "translation": "...",
#          "fromCache": false, "qualityScore": 70, "qaPass": true}]}

# 5. 数字一致性 QA 检查（同 Rust 逻辑）
# 提取源文本中的数字，检查译文中是否都存在

# 6. 保存 job_segments 到 SQLite

# 7. 更新 job status = 'succeeded'
```

**Lambda 调用注意事项：**
- `access_token` 从 session store 获取（不是从请求 header）
- Lambda 的 API Gateway 使用 JWT Authorizer，token 必须有效
- 并发请求：`asyncio.gather` 同时发送多个批次

### 7.3 术语表（routes/glossary.py）

```
GET  /api/glossary              → 所有已认证用户
POST /api/glossary/terms        → 需要 manager 或 super_admin
PATCH /api/glossary/terms/{id}  → 需要 manager 或 super_admin
DELETE /api/glossary/terms/{id} → 需要 manager 或 super_admin
GET  /api/glossary/audit-logs   → 需要 manager 或 super_admin
```

每次写操作都要在 `glossary_audit_logs` 记录：
- action: 'create' | 'update' | 'delete'
- actor: current_user.email
- before_json / after_json

### 7.4 模板（routes/templates.py）

```
GET    /api/templates              → 所有已认证用户
POST   /api/templates              → 需要 manager 或 super_admin（multipart 上传）
PATCH  /api/templates/{id}         → 需要 manager 或 super_admin
DELETE /api/templates/{id}         → 需要 manager 或 super_admin
```

### 7.5 用户管理（routes/users.py）

```
GET /api/users                      → 只有 super_admin
PUT /api/users/{email}/role         → 只有 super_admin
  Body: {"role": "super_admin" | "manager" | "user"}
  自保护规则: 如果操作者是目标且是最后一个 super_admin，拒绝降级
  每次变更写入 role_audit_log

GET /api/audit-logs                 → manager 和 super_admin
  查询参数: action=, from=, to=, page=（默认1，每页100条）
  UNION ALL 查询 glossary_audit_logs 和 role_audit_log
  按时间降序排列
```

### 7.6 文件下载（routes/files.py）

```
GET /api/files/{file_id}/download
  - 从 files 表查询 storage_path
  - 返回文件内容（FileResponse）
  - 设置 Content-Disposition: attachment; filename=...（需处理中文文件名 RFC 5987 编码）
```

### 7.7 设置（routes/settings.py）

```
GET /api/settings    → 返回当前用户设置（从 user_settings 表）
PUT /api/settings    → 保存当前用户设置
```

### 7.8 健康检查

```
GET /api/health → {"status": "ok"} （不需要认证）
```

---

## 八、文件解析服务（services/）

### 8.1 DOCX 解析（docx_parser.py）

使用 `python-docx` 提取段落：

```python
from docx import Document

def extract_segments(file_bytes: bytes) -> list[dict]:
    """
    提取 DOCX 中的可翻译段落。
    返回格式:
    [
        {
            "id": "seg-0",
            "order": 0,
            "text": "原文内容",      # 纯文本，保留 **bold** *italic* ~~strike~~ 标记
            "style": "Normal",       # 段落样式名
            "segment_type": "paragraph" | "title"
        }
    ]
    忽略规则:
    - 空段落
    - 代码块样式（SourceCode, Verbatim, Pre 等）
    - 仅包含数字/符号的段落
    """

def is_code_style(style_name: str) -> bool:
    s = style_name.lower().replace(" ", "").replace("-", "").replace("_", "")
    return s in ("sourcecode", "verbatim", "preformatted", "pre", "code")
```

**内联格式处理：**
```
DOCX 的 run 属性 → Markdown 标记
bold=True  → **text**
italic=True → *text*
strike=True → ~~text~~
```

### 8.2 DOCX 写回（docx_exporter.py）

```python
def export_docx(original_bytes: bytes, segments: list[dict]) -> bytes:
    """
    把译文段落写回原始 DOCX，保留所有样式、图片、表格。
    segments 格式: [{"id": "seg-0", "sourceText": "...", "translation": "..."}]
    
    实现策略:
    1. 用 python-docx 打开原始文件
    2. 遍历所有段落，匹配 segment id
    3. 对匹配的段落，清空原有 runs，按译文重建 runs（保留样式）
    4. 写入内存 BytesIO 返回
    """
```

### 8.3 Excel 解析和写回（excel_parser.py / excel_exporter.py）

```python
# 解析：遍历所有 sheet 的所有单元格，提取非空文本
# 写回：原位替换单元格文字，保留格式
import openpyxl

def extract_segments(file_bytes: bytes) -> list[dict]:
    wb = openpyxl.load_workbook(BytesIO(file_bytes))
    segments = []
    for sheet in wb.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value and isinstance(cell.value, str) and cell.value.strip():
                    segments.append({
                        "id": f"{sheet.title}_{cell.coordinate}",
                        "text": cell.value,
                        "sheet": sheet.title,
                        "cell": cell.coordinate
                    })
    return segments
```

### 8.4 PPTX 解析和写回（pptx_parser.py / pptx_exporter.py）

```python
# 解析：遍历所有幻灯片的文本框
from pptx import Presentation

def extract_segments(file_bytes: bytes) -> list[dict]:
    prs = Presentation(BytesIO(file_bytes))
    segments = []
    for slide_idx, slide in enumerate(prs.slides):
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para_idx, para in enumerate(shape.text_frame.paragraphs):
                    text = para.text.strip()
                    if text:
                        segments.append({
                            "id": f"slide{slide_idx}_shape{shape.shape_id}_para{para_idx}",
                            "text": text,
                            ...
                        })
    return segments
```

### 8.5 翻译服务（services/translation.py）

```python
import httpx, asyncio

async def translate_batch(
    segments: list[dict],
    source_lang: str,
    target_lang: str,
    bearer_token: str,
    lambda_url: str,
    batch_size: int = 25,
    timeout: int = 90
) -> list[dict]:
    """
    并发调用 Lambda 翻译服务。
    每批 batch_size 个段落，所有批次同时发出（asyncio.gather）。
    
    Lambda 请求格式:
    POST {lambda_url}/translate/batch
    Authorization: Bearer {bearer_token}
    {
        "sourceLang": "zh-CN",
        "targetLang": "en-US",
        "segments": [{"id": "seg-1", "text": "原文"}]
    }
    
    Lambda 响应格式:
    {
        "segments": [
            {
                "id": "seg-1",
                "translation": "译文",
                "fromCache": false,
                "qualityScore": 70,
                "qaPass": true,
                "qaReason": null
            }
        ]
    }
    """

def check_number_consistency(source: str, translation: str) -> str | None:
    """
    提取源文本中的数字（2位以上或含小数点），
    检查译文中是否都存在，返回错误描述或 None。
    """
```

### 8.6 术语匹配（services/glossary_matcher.py）

```python
def match_glossary_terms(
    db,
    source_lang: str,
    target_lang: str,
    segment_texts: list[str],
    max_terms: int = 100,
    max_prompt_chars: int = 12000
) -> list[dict]:
    """
    从本地 SQLite glossary_terms 表中匹配出现在段落文本中的术语。
    用于构建发送给 Lambda 的 system_prompt（追加在标准提示词之后）。
    """
```

---

## 九、完整 API 响应格式参考

所有响应均为 JSON，错误格式统一：
```json
{"error": "错误描述"}
```

### 任务对象格式
```json
{
    "id": "uuid",
    "status": "queued|running|succeeded|failed",
    "progress": 0,
    "payload": {
        "fileName": "文件名.docx",
        "sourceLang": "zh-CN",
        "targetLang": "en-US",
        "storedPath": "存储文件名",
        "bearerToken": "..."
    },
    "result": null,
    "errorMessage": null,
    "createdAt": "2024-01-01T00:00:00Z",
    "finishedAt": null
}
```

### 翻译段落格式（job_segments 表对应）
```json
{
    "id": "seg-0",
    "order": 0,
    "sourceText": "原文",
    "draftTranslation": "译文",
    "styleName": "Normal",
    "segmentType": "paragraph",
    "status": "pending|translated|qa_failed",
    "qaPass": true,
    "qaReason": null,
    "fromCache": false,
    "tmQuality": 0
}
```

---

## 十、前端对接注意事项

前端代码**不做任何改动**，以下是前端已有的 API 调用模式，Python 后端必须完全兼容：

1. 所有 API 均在 `/api/` 前缀下
2. 认证通过 cookie `voltdocs_session` 传递（不是 Authorization header）
3. 上传文件使用 `multipart/form-data`
4. `GET /api/auth/me` 在应用加载时调用，用于恢复登录状态
5. 任何 401 响应会触发前端重定向到 `/login?error=session_expired`

---

## 十一、迁移步骤建议

```
阶段 1 — 基础框架（第 1-2 天）
  ✓ 创建 backend-py/ 目录
  ✓ 实现 config.py、database.py
  ✓ 实现 /api/health 端点
  ✓ 实现 session store
  ✓ 验证 SQLite 连接和迁移

阶段 2 — 认证（第 3-5 天）
  ✓ 实现 cognito.py（authorization_url 必须含 identity_provider=MicrosoftTeamsOIDC）
  ✓ 实现 auth/routes.py（login-url, callback, logout, me）
  ✓ 实现 auth/middleware.py（CurrentUser dependency）
  ✓ 端对端测试：登录 → callback → session → /api/auth/me

阶段 3 — 核心路由（第 6-8 天）
  ✓ glossary.py（不涉及文件处理，最简单）
  ✓ templates.py（文件上传）
  ✓ users.py（RBAC 管理）
  ✓ settings.py
  ✓ files.py（下载）

阶段 4 — 文件处理服务（第 9-11 天）
  ✓ docx_parser.py + docx_exporter.py
  ✓ excel_parser.py + excel_exporter.py（新增格式）
  ✓ pptx_parser.py + pptx_exporter.py（新增格式）
  ✓ translation.py（Lambda 调用）
  ✓ pandoc.py（格式转换）

阶段 5 — 路由集成（第 12-13 天）
  ✓ convert.py（接入 pandoc）
  ✓ translation.py（接入文件解析 + Lambda）
  ✓ 所有后台任务测试

阶段 6 — 联调（第 14 天）
  ✓ 前端连接 Python 后端
  ✓ 端对端功能测试
  ✓ 迁移完成，关闭 Rust 后端
```

---

## 十二、测试验收标准

迁移完成后，以下场景必须全部通过：

- [ ] Cognito 登录流程（点击登录 → Microsoft 认证 → 回调 → 进入应用）
- [ ] DOCX 转 Markdown（使用 Pandoc，cwd 正确）
- [ ] Markdown 转 DOCX（含模板选择）
- [ ] DOCX 翻译（上传 → Lambda 调用 → 结果审校 → 导出）
- [ ] Excel 翻译（新格式，openpyxl）
- [ ] PPTX 翻译（新格式，python-pptx）
- [ ] 超级管理员可以修改用户角色
- [ ] 普通管理员可以修改术语表，不能管理用户
- [ ] 普通用户只能使用翻译/转换，不能写入术语表
- [ ] 审计日志正确记录所有写操作
- [ ] session 30 分钟空闲超时、8 小时绝对超时
