import { useEffect, useState } from "react";
import { apiJson, downloadUrl } from "../api/client";

interface TemplateRow {
  id: string;
  file_id: string;
  file_name: string;
  language: string | null;
  tags_json: string;
  created_at: string;
}

export function Templates() {
  const [templates, setTemplates] = useState<TemplateRow[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [tags, setTags] = useState("");
  const [language, setLanguage] = useState("zh-CN");

  async function load() {
    const data = await apiJson<{ templates: TemplateRow[] }>("/templates");
    setTemplates(data.templates);
  }

  useEffect(() => {
    void load();
  }, []);

  async function upload() {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("tags", tags);
    form.append("language", language);
    await apiJson("/templates", { method: "POST", body: form });
    setFile(null);
    setTags("");
    await load();
  }

  async function remove(id: string) {
    await apiJson(`/templates/${id}`, { method: "DELETE" });
    await load();
  }

  return (
    <>
      <header className="page-header">
        <h1>模板管理</h1>
        <p>模板文件保存在服务器本地 volume，元数据保存在本地数据库。</p>
      </header>
      <section className="panel form">
        <label>
          模板文件
          <input type="file" accept=".docx" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
        </label>
        <div className="row">
          <label>
            语言
            <select value={language} onChange={(event) => setLanguage(event.target.value)}>
              <option value="zh-CN">中文</option>
              <option value="en-US">英文</option>
              <option value="ja-JP">日语</option>
            </select>
          </label>
          <label>
            标签
            <input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="英文版,客户定制" />
          </label>
        </div>
        <button disabled={!file} onClick={upload}>上传模板</button>
      </section>
      <section className="panel" style={{ marginTop: 16 }}>
        <h2>模板列表</h2>
        <table>
          <thead>
            <tr>
              <th>文件名</th>
              <th>语言</th>
              <th>标签</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {templates.map((template) => (
              <tr key={template.id}>
                <td>{template.file_name}</td>
                <td>{template.language}</td>
                <td>{JSON.parse(template.tags_json || "[]").join(", ")}</td>
                <td>{new Date(template.created_at).toLocaleString()}</td>
                <td className="row">
                  <a className="button secondary" href={downloadUrl(`/files/${template.file_id}/download`)}>下载</a>
                  <button className="secondary" onClick={() => void remove(template.id)}>删除</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}

