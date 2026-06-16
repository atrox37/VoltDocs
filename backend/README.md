# VoltDocs Backend

FastAPI 后端：文档翻译、转换、术语库、用户权限。

> 完整说明见项目根目录 [README.md](../README.md)。

## 快速启动

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

copy .env.example .env
# 本地开发：REQUIRE_AUTH=false，配置 AWS 凭证或 BEDROCK_AWS_PROFILE

python -m uvicorn main:app --host 127.0.0.1 --port 8080 --reload
```

API 地址：http://127.0.0.1:8080

**Windows `WinError 10013`**：改用 `127.0.0.1` 而非 `0.0.0.0`；或放行防火墙 8080 端口。

## 核心模块

```
backend/
├── auth/                   # Cognito OAuth、Session 中间件
├── routes/
│   ├── translation.py      # 翻译任务、导出、审校数据
│   ├── convert.py          # MD → DOCX
│   ├── glossary.py         # 术语库 CRUD / 导入导出
│   └── users.py            # 用户角色管理
├── services/
│   ├── translation.py      # Bedrock 批量翻译编排
│   ├── qa_hybrid.py        # QA + AI 修复流水线
│   ├── bedrock.py          # Bedrock Converse API
│   ├── docx_parser.py      # DOCX 分段（含目录字段）
│   ├── docx_exporter.py    # DOCX 写回（保留绘图/目录域）
│   └── docx/
│       ├── fields.py       # TOC / PAGEREF 标题提取与替换
│       └── markup.py       # 加粗标记、译文清洗
└── tests/                  # pytest（pnpm test 从根目录运行）
```

## 配置要点

| 变量 | 默认 | 说明 |
|------|------|------|
| `REQUIRE_AUTH` | `false` | 生产环境设为 `true` |
| `BEDROCK_MODEL_ID` | Nova Lite | 翻译 |
| `QA_AI_MODEL_ID` | Nova Micro | QA 复核 |
| `QA_REPAIR_MAX_ATTEMPTS` | `1` | 建议 `2` |
| `TRANSLATION_BATCH_MAX_SEGMENTS` | `40` | 过大易漏译 |

## 支持格式

| 格式 | 翻译 | 说明 |
|------|------|------|
| .docx | ✅ | 段落、目录、文本框、内联格式 |
| .xlsx | ✅ | 单元格级翻译 |
| .md | ✅ | |
| .pptx | ❌ | 暂未启用 |

## 生产部署

见 [deploy/README.md](../deploy/README.md)。Docker 镜像见 `backend/Dockerfile`。
