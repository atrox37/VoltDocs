import { useEffect, useMemo, useState } from "react";
import { createTranslationJob, exportTranslation, getTranslationJob } from "../api/jobs";
import { downloadUrl } from "../api/client";
import type { Job, TranslationSegment } from "../types/api";

function parseResult(job: Job | null) {
  if (!job?.result_json) return null;
  try {
    return JSON.parse(job.result_json) as {
      fileName: string;
      sourceLang: string;
      targetLang: string;
      segments: TranslationSegment[];
    };
  } catch {
    return null;
  }
}

export function Translate() {
  const [file, setFile] = useState<File | null>(null);
  const [sourceLang, setSourceLang] = useState("zh-CN");
  const [targetLang, setTargetLang] = useState("en-US");
  const [job, setJob] = useState<Job | null>(null);
  const [segments, setSegments] = useState<TranslationSegment[]>([]);
  const [download, setDownload] = useState<{ fileId: string; fileName: string } | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const timer = window.setInterval(async () => {
      setJob(await getTranslationJob(job.id));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [job]);

  const result = useMemo(() => parseResult(job), [job]);

  useEffect(() => {
    if (result?.segments) setSegments(result.segments);
  }, [result]);

  async function submit() {
    if (!file) return;
    setError("");
    setDownload(null);
    try {
      setJob(await createTranslationJob(file, sourceLang, targetLang));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function exportDocx() {
    if (!job) return;
    const output = await exportTranslation(job.id, segments.map((segment) => ({
      sourceText: segment.sourceText,
      translation: segment.draftTranslation
    })));
    setDownload(output);
  }

  return (
    <>
      <header className="page-header">
        <h1>文档翻译</h1>
        <p>上传 DOCX 后由后端解析段落、筛选术语并调用 AWS 翻译。</p>
      </header>
      <section className="panel form">
        <label>
          DOCX 文件
          <input type="file" accept=".docx" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
        </label>
        <div className="row">
          <label>
            源语言
            <select value={sourceLang} onChange={(event) => setSourceLang(event.target.value)}>
              <option value="zh-CN">中文</option>
              <option value="en-US">英文</option>
            </select>
          </label>
          <label>
            目标语言
            <select value={targetLang} onChange={(event) => setTargetLang(event.target.value)}>
              <option value="en-US">英文</option>
              <option value="zh-CN">中文</option>
              <option value="ja-JP">日语</option>
            </select>
          </label>
        </div>
        <div className="row">
          <button disabled={!file} onClick={submit}>提交翻译任务</button>
          {job && <span className={`status ${job.status}`}>{job.status} {job.progress}%</span>}
          {error && <span className="muted">{error}</span>}
        </div>
      </section>
      {segments.length > 0 && (
        <section className="panel" style={{ marginTop: 16 }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h2>审校段落</h2>
            <button onClick={exportDocx}>导出 DOCX</button>
          </div>
          <table>
            <thead>
              <tr>
                <th style={{ width: 70 }}>序号</th>
                <th>原文</th>
                <th>译文</th>
                <th style={{ width: 120 }}>QA</th>
              </tr>
            </thead>
            <tbody>
              {segments.map((segment, index) => (
                <tr key={segment.id}>
                  <td>{index + 1}</td>
                  <td>{segment.sourceText}</td>
                  <td>
                    <textarea
                      value={segment.draftTranslation}
                      onChange={(event) => {
                        const next = [...segments];
                        next[index] = { ...segment, draftTranslation: event.target.value };
                        setSegments(next);
                      }}
                    />
                  </td>
                  <td>{segment.qaPass ? "通过" : segment.qaReason}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {download && <p><a className="button" href={downloadUrl(`/files/${download.fileId}/download`)}>下载 {download.fileName}</a></p>}
        </section>
      )}
    </>
  );
}

