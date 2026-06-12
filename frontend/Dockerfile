FROM m.daocloud.io/docker.io/library/node:20-bookworm AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json frontend/tsconfig.json frontend/vite.config.ts frontend/index.html ./
COPY frontend/public ./public
COPY frontend/src ./src
RUN npm ci && npm run build

FROM nginx:1.18.0
COPY --from=build /app/dist /usr/share/nginx/html
COPY infra/nginx/default.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
