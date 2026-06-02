import { useEffect, useState } from "react";
import { createConvertJob, getConvertJob } from "../api/jobs";
import { downloadUrl } from "../api/client";
import type { Job } from "../types/api";

function parseResult(job: Job | null) {
  if (!job?.result_json) return null;
  try {
    return JSON.parse(job.result_json) as { fileId: string; fileName: string };
  } catch {
    return null;
  }
}

export function Convert() {
  const [file, setFile] = useState<File | null>(null);
  const [format, setFormat] = useState("docx");
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const timer = window.setInterval(async () => {
      setJob(await getConvertJob(job.id));
    }, 1200);
    return () => window.clearInterval(timer);
  }, [job]);

  async function submit() {
    if (!file) return;
    setError("");
    try {
      setJob(await createConvertJob(file, format));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const result = parseResult(job);

  return (
    <>
      <header className="page-header">
        <h1>格式转换</h1>
        <p>文件上传到后端后进入任务队列，由服务器调用 Pandoc。</p>
      </header>
      <section className="panel form">
        <label>
          文件
          <input type="file" accept=".md,.markdown,.docx" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
        </label>
        <label>
          输出格式
          <select value={format} onChange={(event) => setFormat(event.target.value)}>
            <option value="docx">DOCX</option>
            <option value="md">Markdown</option>
          </select>
        </label>
        <div className="row">
          <button disabled={!file} onClick={submit}>提交转换任务</button>
          {error && <span className="muted">{error}</span>}
        </div>
      </section>
      {job && (
        <section className="panel" style={{ marginTop: 16 }}>
          <h2>任务状态</h2>
          <p><span className={`status ${job.status}`}>{job.status}</span> 进度 {job.progress}%</p>
          {job.error_message && <p className="muted">{job.error_message}</p>}
          {result && <a className="button" href={downloadUrl(`/files/${result.fileId}/download`)}>下载 {result.fileName}</a>}
        </section>
      )}
    </>
  );
}

