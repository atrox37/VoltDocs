import { useEffect, useState } from "react";
import { apiJson } from "../api/client";

interface TermRow {
  id: string;
  source_lang: string;
  target_lang: string;
  source_term: string;
  target_term: string;
  context: string | null;
  enabled: number;
  priority: number;
}

export function Glossary() {
  const [terms, setTerms] = useState<TermRow[]>([]);
  const [sourceTerm, setSourceTerm] = useState("");
  const [targetTerm, setTargetTerm] = useState("");
  const [csv, setCsv] = useState("sourceTerm,targetTerm,context,priority\n固定框架,Fixed Frame,main structure,10");
  const [preview, setPreview] = useState<{ valid?: unknown[]; errors?: unknown[] } | null>(null);

  async function load() {
    const data = await apiJson<{ terms: TermRow[] }>("/glossary");
    setTerms(data.terms);
  }

  useEffect(() => {
    void load();
  }, []);

  async function addTerm() {
    await apiJson("/glossary/terms", {
      method: "POST",
      body: JSON.stringify({ sourceTerm, targetTerm, priority: 0 })
    });
    setSourceTerm("");
    setTargetTerm("");
    await load();
  }

  async function toggle(term: TermRow) {
    await apiJson(`/glossary/terms/${term.id}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled: term.enabled !== 1 })
    });
    await load();
  }

  async function previewImport() {
    setPreview(await apiJson("/glossary/import/preview", {
      method: "POST",
      headers: { "content-type": "text/plain" },
      body: csv
    }));
  }

  async function commitImport() {
    const rows = (preview as { valid?: unknown[] } | null)?.valid ?? [];
    await apiJson("/glossary/import/commit", {
      method: "POST",
      body: JSON.stringify({ rows })
    });
    setPreview(null);
    await load();
  }

  return (
    <>
      <header className="page-header">
        <h1>术语表</h1>
        <p>术语可大量导入，但翻译时后端只筛选当前批次命中的术语进入 prompt。</p>
      </header>
      <section className="grid two">
        <div className="panel form">
          <h2>新增术语</h2>
          <label>源术语<input value={sourceTerm} onChange={(event) => setSourceTerm(event.target.value)} /></label>
          <label>目标术语<input value={targetTerm} onChange={(event) => setTargetTerm(event.target.value)} /></label>
          <button disabled={!sourceTerm || !targetTerm} onClick={addTerm}>新增</button>
        </div>
        <div className="panel form">
          <h2>CSV 导入</h2>
          <textarea value={csv} onChange={(event) => setCsv(event.target.value)} />
          <div className="row">
            <button onClick={previewImport}>预览</button>
            <button className="secondary" disabled={!preview} onClick={commitImport}>确认导入</button>
          </div>
          {preview && <p className="muted">有效 {(preview.valid ?? []).length} 条，错误 {(preview.errors ?? []).length} 条</p>}
        </div>
      </section>
      <section className="panel" style={{ marginTop: 16 }}>
        <h2>术语列表</h2>
        <table>
          <thead>
            <tr>
              <th>源语言</th>
              <th>目标语言</th>
              <th>源术语</th>
              <th>目标术语</th>
              <th>上下文</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {terms.map((term) => (
              <tr key={term.id}>
                <td>{term.source_lang}</td>
                <td>{term.target_lang}</td>
                <td>{term.source_term}</td>
                <td>{term.target_term}</td>
                <td>{term.context}</td>
                <td><button className="secondary" onClick={() => void toggle(term)}>{term.enabled ? "启用" : "禁用"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}

