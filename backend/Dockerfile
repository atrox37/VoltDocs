FROM m.daocloud.io/docker.io/library/node:20-bookworm AS deps
WORKDIR /app
COPY package.json ./
RUN npm install

FROM m.daocloud.io/docker.io/library/node:20-bookworm AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY package.json tsconfig.json ./
COPY src ./src
RUN npm run build

FROM m.daocloud.io/docker.io/library/node:20-bookworm-slim
WORKDIR /app
RUN apt-get update \
  && apt-get install -y --no-install-recommends pandoc ca-certificates \
  && rm -rf /var/lib/apt/lists/*
COPY package.json ./
COPY --from=deps /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
ENV NODE_ENV=production
ENV DATA_DIR=/app/data
EXPOSE 8080
CMD ["node", "dist/server.js"]
