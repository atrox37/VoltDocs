import { get, uploadFile } from "./client";

export interface ConvertJob {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  progress: number;
  payload?: {
    fileName: string;
    outputFormat: string;
    templateId?: string;
  };
  result?: {
    fileId: string;
    fileName: string;
  };
  errorMessage?: string;
  createdAt: string;
  finishedAt?: string;
}

export function createConvertJob(
  file: File,
  outputFormat: string,
  templateId?: string,
  outputFileName?: string
) {
  const fields: Record<string, string> = { outputFormat };
  if (templateId) fields.templateId = templateId;
  if (outputFileName?.trim()) fields.outputFileName = outputFileName.trim();
  return uploadFile<{ id: string; status: string }>("/convert/jobs", file, fields);
}

export function listConvertJobs() {
  return get<{ jobs: ConvertJob[] }>("/convert/jobs");
}

export function getConvertJob(jobId: string) {
  return get<ConvertJob>(`/convert/jobs/${jobId}`);
}

export function getConvertProgress(jobId: string) {
  return get<{ status: string; progress: number }>(`/convert/jobs/${jobId}/progress`);
}
