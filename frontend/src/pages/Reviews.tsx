import { useEffect, useState } from "react";
import { apiJson } from "../api/client";

interface ReviewRow {
  id: string;
  file_name: string;
  source_lang: string;
  target_lang: string;
  status: string;
  updated_at: string;
}

export function Reviews() {
  const [reviews, setReviews] = useState<ReviewRow[]>([]);

  useEffect(() => {
    apiJson<{ reviews: ReviewRow[] }>("/reviews").then((data) => setReviews(data.reviews)).catch(() => setReviews([]));
  }, []);

  return (
    <>
      <header className="page-header">
        <h1>审校记录</h1>
        <p>服务端审校归档入口。当前翻译页面已支持导出文件，后续可在这里补完整归档报告。</p>
      </header>
      <section className="panel">
        <table>
          <thead>
            <tr>
              <th>文件</th>
              <th>语言对</th>
              <th>状态</th>
              <th>更新时间</th>
            </tr>
          </thead>
          <tbody>
            {reviews.map((review) => (
              <tr key={review.id}>
                <td>{review.file_name}</td>
                <td>{review.source_lang} → {review.target_lang}</td>
                <td><span className="status">{review.status}</span></td>
                <td>{new Date(review.updated_at).toLocaleString()}</td>
              </tr>
            ))}
            {reviews.length === 0 && (
              <tr>
                <td colSpan={4} className="muted">暂无服务端审校记录。</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </>
  );
}

