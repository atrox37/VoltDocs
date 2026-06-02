# VoltDocs Web Docker 部署

## 数据目录

生产环境建议使用固定宿主机目录：

```bash
sudo mkdir -p /opt/voltdocs/data
sudo chown -R 1000:1000 /opt/voltdocs/data
```

该目录会挂载到 API 容器的 `/app/data`：

```text
/opt/voltdocs/data/
├── db/
├── templates/
├── uploads/
├── outputs/
├── archives/
└── jobs/
```

## 启动

```bash
cp .env.example .env
docker compose up -d --build
```

默认 Web 入口：

```text
http://server-ip:8088
```

## Pandoc 并发

默认：

```text
PANDOC_MAX_CONCURRENCY=1
PANDOC_TIMEOUT_SECONDS=300
```

当前实现使用单 worker 顺序执行重型任务，等价于并发 1。后续如果服务器资源允许，可以扩展 worker 池并尊重 `PANDOC_MAX_CONCURRENCY`。

## AWS

V0.1.1 仅需要配置 Lambda URL：

```text
TRANSLATION_LAMBDA_URL=https://xxx.execute-api.us-east-1.amazonaws.com/prod
```

如果不配置，后端会使用本地 mock 翻译，返回 `[目标语言] 原文`，方便离线调试。

## 备份

至少备份：

```text
/opt/voltdocs/data/db
/opt/voltdocs/data/templates
/opt/voltdocs/data/archives
```

`uploads`、`outputs`、`jobs` 可以按保留策略清理。

