#!/bin/bash
# VoltDocs HTTPS 部署脚本
# 在虚拟机（192.168.30.10）上以 root 或 sudo 运行

set -e

SERVER_IP="192.168.30.10"
INTERNAL_PORT="8088"   # nginx 监听端口（宿主机映射到 18088）
BACKEND_PORT="8080"    # Actix-Web 后端端口
FRONTEND_DIST="/var/www/voltdocs/dist"

echo "=== 1. 安装 nginx ==="
apt-get update -y && apt-get install -y nginx openssl

echo "=== 2. 生成自签 TLS 证书 ==="
mkdir -p /etc/nginx/ssl
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/voltdocs.key \
  -out /etc/nginx/ssl/voltdocs.crt \
  -subj "/CN=${SERVER_IP}" \
  -addext "subjectAltName=IP:${SERVER_IP}"

echo "=== 3. 写入 nginx 配置 ==="
cat > /etc/nginx/conf.d/voltdocs.conf << EOF
server {
    listen ${INTERNAL_PORT} ssl;
    server_name ${SERVER_IP};

    ssl_certificate     /etc/nginx/ssl/voltdocs.crt;
    ssl_certificate_key /etc/nginx/ssl/voltdocs.key;
    ssl_protocols       TLSv1.2 TLSv1.3;

    # 前端静态文件
    location / {
        root ${FRONTEND_DIST};
        try_files \$uri \$uri/ /index.html;
    }

    # 后端 API 反向代理
    location /api/ {
        proxy_pass         http://127.0.0.1:${BACKEND_PORT};
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto https;
        proxy_read_timeout 300s;
        client_max_body_size 100m;
    }
}

# 可选：HTTP 自动跳转 HTTPS
server {
    listen 80;
    server_name ${SERVER_IP};
    return 301 https://\$host:${INTERNAL_PORT}\$request_uri;
}
EOF

echo "=== 4. 测试并重启 nginx ==="
nginx -t && systemctl restart nginx && systemctl enable nginx

echo ""
echo "=== 完成！==="
echo "访问地址: https://${SERVER_IP}:18088"
echo "回调地址: https://${SERVER_IP}:18088/api/auth/callback"
echo ""
echo "下一步："
echo "1. 将 frontend/dist 复制到 ${FRONTEND_DIST}"
echo "2. 更新 backend-rs/.env 中的 COGNITO_REDIRECT_URI"
echo "3. 在 AWS Cognito 控制台添加回调 URL"
