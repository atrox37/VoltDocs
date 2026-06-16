# V0.1.1 实现说明

## 已实现

- Vite React 前端，不依赖 Tauri。
- Express API 后端。
- SQLite 本地数据库。
- 本地模板文件管理。
- 本地术语表 CRUD 与 CSV 导入。
- 术语匹配器：翻译前只筛选当前 batch 命中的术语。
- Pandoc 转换任务队列。
- DOCX 段落提取、翻译任务和基础 DOCX 导出。
- Docker Compose 单服务器部署。

## 重要限制

- DOCX 导出保留基础段落文本替换，不等价于旧 Tauri Rust 实现的完整 Word XML 格式处理。
- 当前 job worker 是单 worker，实际 Pandoc 并发为 1。
- Cognito JWT 目前只做 bearer payload 解析；生产开启 `REQUIRE_AUTH=true` 前应补 JWKS 签名验证。
- CSV 解析为简单逗号分隔，不支持复杂引号转义；术语表正式导入 XLSX/CSV 时建议使用成熟 parser。
- Lambda URL 未配置时会使用 mock 翻译。

## 下一步建议

1. 把旧项目 `src-tauri/src/translation.rs` 中更完整的 DOCX XML 处理迁移到后端 service。
2. 增加 Cognito JWKS 校验。
3. 增加任务清理和备份脚本。
4. 将审校保存接入翻译页面，形成完整服务端归档。
5. 增加 Excel 审校报告导出。

