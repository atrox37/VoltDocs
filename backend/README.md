# VoltDocs Python Backend

新的 Python 后端目录，按 `docs/python-migration-plan.md` 创建，用于替代 `backend-rs/`。

当前已完成：

- `FastAPI` 入口和 `/api/*` 路由骨架
- Cognito 登录回调、cookie session、开发模式免认证
- SQLite 自动建表，兼容现有表结构
- 术语库、模板、用户角色、审计日志、设置、文件下载
- 转换任务 `/api/convert/*`
- 翻译任务 `/api/translation/*`
- DOCX / XLSX / PPTX 基础解析与导出

## 虚拟环境

已在本目录创建本地虚拟环境：

```powershell
D:\Project\VoltDocs\backend-py\.venv
```

激活方式：

```powershell
cd D:\Project\VoltDocs\backend-py
.\.venv\Scripts\Activate.ps1
```

不激活也可以，直接用虚拟环境里的 Python 启动。

## 启动方式

推荐：

```powershell
cd D:\Project\VoltDocs\backend-py
.\.venv\Scripts\python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

如果已经激活虚拟环境，也可以：

```powershell
cd D:\Project\VoltDocs\backend-py
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

## 配置说明

- `.env` 已从 `backend-rs/.env` 复制到本目录。
- `DATA_DIR=./data` 默认会解析到 `backend-py/data`。
- 如果你要直接复用 `backend-rs/data`，需要把 `.env` 里的 `DATA_DIR` 改成共享路径。
- `Pandoc` 仍依赖本机 `pandoc` 可执行文件。

## 验证

本地已完成：

- 虚拟环境创建成功
- 依赖已安装到 `.venv`
- `main.py` 导入验证通过
- `compileall backend-py` 通过
