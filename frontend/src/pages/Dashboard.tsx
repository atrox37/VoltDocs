import { Link } from "react-router-dom";

export function Dashboard() {
  return (
    <>
      <header className="page-header">
        <h1>VoltDocs 工作台</h1>
        <p>单服务器 Web 版，文件处理在本地 API 中执行，AI 翻译继续对接 AWS。</p>
      </header>
      <section className="grid three">
        <div className="card">
          <h3>文档翻译</h3>
          <p className="muted">上传 DOCX，提取段落，调用 AWS 翻译，审校后导出 Word。</p>
          <Link className="button" to="/translate">开始翻译</Link>
        </div>
        <div className="card">
          <h3>格式转换</h3>
          <p className="muted">通过后端队列调用 Pandoc，避免高并发拖垮服务器。</p>
          <Link className="button" to="/convert">创建转换任务</Link>
        </div>
        <div className="card">
          <h3>术语表</h3>
          <p className="muted">术语存本地数据库，翻译时只注入当前批次命中的术语。</p>
          <Link className="button" to="/glossary">管理术语</Link>
        </div>
      </section>
      <section className="panel" style={{ marginTop: 16 }}>
        <h2>V0.1.1 约束</h2>
        <div className="grid three">
          <p><strong>本地持久化</strong><br /><span className="muted">模板、任务、归档、数据库写入 Docker volume。</span></p>
          <p><strong>Pandoc 队列</strong><br /><span className="muted">转换任务排队执行，默认同一时间只跑一个 Pandoc。</span></p>
          <p><strong>AWS 保留</strong><br /><span className="muted">Cognito、Lambda、Bedrock 继续作为认证和 AI 翻译能力。</span></p>
        </div>
      </section>
    </>
  );
}

