# VoltDocs 部署说明

## 架构

```
内网用户
  │
  ▼
网关机 192.168.30.10:18088（固定）
  │  端口映射：192.168.30.10:18088 → 虚拟机:8088
  ▼
虚拟机（内网 DHCP，IP 可变）
  ├── Docker: web 容器 (nginx，监听 8088)
  │     ├── 服务前端静态文件
  │     └── 反向代理 /api/* → api:8080
  └── Docker: api 容器 (FastAPI，监听 8080)
        └── 数据卷：/opt/voltdocs/data
```

用户访问地址：`http://192.168.30.10:18088`

---

## 首次部署步骤

### 1. 上传代码到虚拟机

```bash
# git clone（推荐）
git clone <仓库地址> /opt/voltdocs/app
cd /opt/voltdocs/app

# 或 scp
scp -r ./VoltDocs user@<虚拟机IP>:/opt/voltdocs/app
```

### 2. 配置环境变量

```bash
cp backend/.env.example backend/.env
nano backend/.env
```

必填项：

| 配置项 | 示例值 |
|--------|--------|
| `REQUIRE_AUTH` | `true` |
| `INITIAL_ADMIN_EMAIL` | `zhiyuan.wang@voltageenergy.com` |
| `AWS_ACCESS_KEY_ID` | `AKIA...` |
| `AWS_SECRET_ACCESS_KEY` | `...` |
| `BEDROCK_REGION` | `us-east-1` |
| `COGNITO_DOMAIN` | `https://us-east-1fluobqcda.auth.us-east-1.amazoncognito.com` |
| `COGNITO_CLIENT_ID` | `2fnmsk89dt0066l25kmi68m7qp` |
| `COGNITO_REDIRECT_URI` | `http://192.168.30.10:18088/api/auth/callback` |
| `FRONTEND_URL` | `http://192.168.30.10:18088` |

### 3. 运行部署脚本

```bash
cd /opt/voltdocs/app
sudo bash deploy/setup-https.sh
```

脚本会自动：
- 安装 Docker（如未安装）
- 创建数据目录 `/opt/voltdocs/data`
- 自动写入 `FRONTEND_URL` 和 `COGNITO_REDIRECT_URI`
- 构建并启动容器
- 健康检查

### 4. 配置 AWS Cognito（仅首次）

在 AWS 控制台 → Cognito → 用户池 → 应用客户端 → 编辑：
- **允许的回调 URL** 添加：`http://192.168.30.10:18088/api/auth/callback`
- **允许的登出 URL** 添加：`http://192.168.30.10:18088`

### 5. 配置网关机端口映射

确保网关机 `192.168.30.10` 将 `18088` 端口转发到虚拟机的 `8088` 端口。

Linux 网关机示例：
```bash
# 假设虚拟机内网 IP 为 10.0.0.5
iptables -t nat -A PREROUTING -p tcp --dport 18088 -j DNAT --to-destination 10.0.0.5:8088
iptables -t nat -A POSTROUTING -j MASQUERADE
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

```bash
docker compose ps                    # 查看运行状态
docker compose logs -f               # 查看实时日志
docker compose logs -f api           # 只看后端日志
docker compose restart               # 重启所有服务
docker compose down                  # 停止服务
```

## 数据备份

```bash
# 备份数据库
cp /opt/voltdocs/data/db/voltdocs.db ~/voltdocs-backup-$(date +%Y%m%d).db

# 备份完整数据
tar -czf ~/voltdocs-data-$(date +%Y%m%d).tar.gz /opt/voltdocs/data/
```
