import { apiJson } from "./client";
import type { Job } from "../types/api";

export async function createConvertJob(file: File, outputFormat: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("outputFormat", outputFormat);
  return apiJson<Job>("/convert/jobs", { method: "POST", body: form });
}

export async function createTranslationJob(file: File, sourceLang: string, targetLang: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("sourceLang", sourceLang);
  form.append("targetLang", targetLang);
  return apiJson<Job>("/translation/jobs", { method: "POST", body: form });
}

export async function getConvertJob(jobId: string) {
  return apiJson<Job>(`/convert/jobs/${jobId}`);
}

export async function getTranslationJob(jobId: string) {
  return apiJson<Job>(`/translation/jobs/${jobId}`);
}

export async function exportTranslation(jobId: string, segments: unknown[]) {
  return apiJson<{ fileId: string; fileName: string; downloadUrl: string }>(`/translation/jobs/${jobId}/export`, {
    method: "POST",
    body: JSON.stringify({ segments })
  });
}

