# VoltDocs 部署说明

## 架构

```
外网/内网用户
  │
  ▼
网关机 (固定 IP: 192.168.30.10)
  │  端口映射: 18088 (HTTPS) → 虚拟机:8088
  ▼
虚拟机 (内网 DHCP，IP 可变)
  │
  ├── Docker: web 容器 (Nginx)
  │     ├── 监听: 8088 (HTTP), 18088 (HTTPS)
  │     ├── 服务前端静态文件
  │     └── 反向代理 /api/* → api:8080
  │
  └── Docker: api 容器 (FastAPI)
        └── 监听: 8080
             └── 数据卷: /opt/voltdocs/data
```

**用户访问地址**：`http://192.168.30.10:18088`

---

## 首次部署步骤

### 1. 上传代码到虚拟机

```bash
# 方式一：git clone（推荐）
git clone <仓库地址> /opt/voltdocs/app
cd /opt/voltdocs/app

# 方式二：scp 上传
scp -r ./VoltDocs user@<虚拟机IP>:/opt/voltdocs/app
```

### 2. 配置环境变量

```bash
cd /opt/voltdocs/app
cp backend/.env.example backend/.env
nano backend/.env
```

**必填配置项**：

| 配置项 | 示例值 | 说明 |
|--------|--------|------|
| `REQUIRE_AUTH` | `true` | 启用 Cognito 认证 |
| `INITIAL_ADMIN_EMAIL` | `admin@voltageenergy.com` | 首个超级管理员邮箱 |
| `AWS_ACCESS_KEY_ID` | `AKIA...` | AWS 访问密钥 |
| `AWS_SECRET_ACCESS_KEY` | `...` | AWS 秘密密钥 |
| `BEDROCK_REGION` | `us-east-1` | AWS 区域 |
| `COGNITO_DOMAIN` | `https://xxx.auth.us-east-1.amazoncognito.com` | Cognito 域名 |
| `COGNITO_CLIENT_ID` | `2fnmsk89dt0066l25kmi68m7qp` | 应用客户端 ID |
| `COGNITO_CLIENT_SECRET` | `...` | 应用客户端密钥 |
| `COGNITO_REDIRECT_URI` | `http://192.168.30.10:18088/api/auth/callback` | OAuth 回调地址 |
| `FRONTEND_URL` | `http://192.168.30.10:18088` | 前端地址 |

### 3. 运行部署脚本

```bash
cd /opt/voltdocs/app
sudo bash deploy/setup-https.sh
```

脚本自动执行：
- 安装 Docker（如未安装）
- 创建数据目录 `/opt/voltdocs/data`
- 写入 `FRONTEND_URL` 和 `COGNITO_REDIRECT_URI` 到配置
- 构建并启动容器
- 健康检查

### 4. 配置 AWS Cognito（仅首次）

在 AWS Console → Cognito → 用户池 → 应用客户端 → 编辑：

- **允许的回调 URL** 添加：
  ```
  http://192.168.30.10:18088/api/auth/callback
  ```
- **允许的登出 URL** 添加：
  ```
  http://192.168.30.10:18088
  ```

### 5. 配置网关机端口映射

确保网关机 `192.168.30.10` 将 `18088` 端口转发到虚拟机的 `8088` 端口。

**Linux 网关机配置示例**（假设虚拟机内网 IP 为 `10.0.0.5`）：

```bash
# NAT 转发规则
iptables -t nat -A PREROUTING -p tcp --dport 18088 -j DNAT --to-destination 10.0.0.5:8088
iptables -t nat -A POSTROUTING -j MASQUERADE

# 持久化保存（Debian/Ubuntu）
apt-get install iptables-persistent
netfilter-persistent save
```

---

## 更新部署

```bash
cd /opt/voltdocs/app
git pull
docker compose build
docker compose up -d
```

---

## 常用运维命令

### 容器管理

```bash
docker compose ps                # 查看运行状态
docker compose logs -f           # 查看实时日志
docker compose logs -f api       # 只看后端日志
docker compose logs -f web       # 只看前端日志
docker compose restart           # 重启所有服务
docker compose restart api       # 只重启后端
docker compose down              # 停止所有服务
docker compose up -d             # 后台启动
```

### 进入容器调试

```bash
docker exec -it voltdocs-api-1 sh   # 进入后端容器
docker exec -it voltdocs-web-1 sh   # 进入前端容器
```

### 数据库操作

```bash
# 连接数据库
docker exec -it voltdocs-api-1 sqlite3 /app/data/db/voltdocs.db

# 查看表结构
.docker exec -it voltdocs-api-1 sqlite3 /app/data/db/voltdocs.db ".schema"
```

---

## 数据备份与恢复

### 备份

```bash
# 备份数据库
cp /opt/voltdocs/data/db/voltdocs.db ~/voltdocs-backup-$(date +%Y%m%d).db

# 备份完整数据
tar -czf ~/voltdocs-data-$(date +%Y%m%d).tar.gz /opt/voltdocs/data/
```

### 恢复

```bash
# 恢复数据库
sudo cp ~/voltdocs-backup-20240101.db /opt/voltdocs/data/db/voltdocs.db

# 恢复完整数据
sudo tar -xzf ~/voltdocs-data-20240101.tar.gz -C /
```

---

## 数据目录结构

```
/opt/voltdocs/data/
├── db/
│   └── voltdocs.db          # SQLite 数据库
├── uploads/                 # 用户上传的源文件
│   └── *.docx / *.xlsx
├── outputs/                 # 翻译/转换后的输出文件
│   └── *-translated.docx
├── templates/               # Word 模板文件
│   └── *.docx
├── jobs/                    # 临时任务文件
└── archives/                # 归档文件
```

---

## SSL/HTTPS 配置

### 证书位置

```
/etc/nginx/ssl/
├── cert.pem      # 服务器证书
└── key.pem       # 私钥
```

### 更新证书

```bash
# 复制新证书
sudo cp your-cert.pem /etc/nginx/ssl/cert.pem
sudo cp your-key.pem /etc/nginx/ssl/key.pem

# 重载 Nginx
docker exec voltdocs-web-1 nginx -s reload
```

---

## 故障排查

### 常见问题

| 问题 | 可能原因 | 解决方案 |
|------|---------|---------|
| 访问页面空白 | 前端构建失败 | 检查 `docker compose logs web` |
| 翻译请求失败 | Bedrock 凭证错误 | 检查 AWS 密钥配置 |
| 文件上传失败 | 目录权限问题 | 检查 `/opt/voltdocs/data` 权限 |
| 登录失败 | Cognito 配置错误 | 检查客户端 ID 和回调地址 |
| 数据库锁定 | 并发写入冲突 | 检查 SQLite WAL 模式 |

### 日志位置

```bash
# 后端日志
docker compose logs -f api

# 前端 Nginx 日志
docker compose logs web

# 系统日志
journalctl -u docker -f
```

---

## 监控（可选）

### 健康检查端点

```bash
curl http://localhost:8080/api/health
```

返回示例：
```json
{
  "status": "ok",
  "version": "1.0.0"
}
```

---

*VoltDocs 部署文档 · Voltage Energy 运维团队*