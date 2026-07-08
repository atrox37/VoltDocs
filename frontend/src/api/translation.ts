import { get, post, uploadFile } from "./client";

export interface TranslationJob {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  progress: number;
  payload?: {
    sourceLang: string;
    targetLang: string;
    fileName: string;
  };
  result?: {
    totalSegments: number;
    sourceLang: string;
    targetLang: string;
    allQaPass?: boolean;
    autoFileId?: string;
    autoFileName?: string;
    tmHits?: number;
    tmStored?: number;
    tmInserted?: number;
    tmUpdated?: number;
    tmSkipped?: number;
    tmPruned?: number;
    qaProfile?: {
      roundCount: number;
      mostCommonRuleName?: string | null;
      ruleCounts: Record<string, number>;
      failureTypes: Record<string, number>;
      stoppedSegments: number;
    } | null;
  };
  errorMessage?: string;
  createdAt: string;
  finishedAt?: string;
}

export interface TranslationSegment {
  id: string;
  order: number;
  sourceText: string;
  draftTranslation: string;
  styleName?: string;
  segmentType: string;
  status: string;
  qaPass: boolean;
  qaReason?: string;
  fromCache: boolean;
  tmQuality: number;
  glossaryDebug?: {
    matchedTerms: Array<{
      source: string;
      target: string;
      context?: string;
    }>;
    contextBefore?: string;
    contextAfter?: string;
    postprocessApplied: boolean;
    postprocessBefore?: string | null;
    postprocessAfter?: string | null;
    finalCheckPassed: boolean;
    finalCheckReason?: string | null;
  } | null;
  qaDebug?: {
    history: Array<{
      round: number;
      qaPass: boolean;
      ruleName?: string | null;
      failureType?: string | null;
      reason?: string | null;
      translation: string;
    }>;
    stoppedEarly: boolean;
    stoppedReason?: string | null;
    finalRuleName?: string | null;
    finalFailureType?: string | null;
  } | null;
}

export interface JobDetail {
  job: TranslationJob;
  segments: TranslationSegment[];
}

export function createTranslationJob(file: File, sourceLang: string, targetLang: string) {
  return uploadFile<{ id: string; status: string }>("/translation/jobs", file, {
    sourceLang,
    targetLang,
  });
}

export function listTranslationJobs() {
  return get<{ jobs: TranslationJob[] }>("/translation/jobs");
}

export function getTranslationJob(jobId: string) {
  return get<JobDetail>(`/translation/jobs/${jobId}`);
}

export function getJobProgress(jobId: string) {
  return get<{ status: string; progress: number }>(`/translation/jobs/${jobId}/progress`);
}

export function exportTranslation(
  jobId: string,
  segments: Array<{ sourceText: string; translation: string }>,
) {
  return post<{ fileId: string; fileName: string; downloadUrl: string }>(
    `/translation/jobs/${jobId}/export`,
    { segments },
  );
}

export async function batchDownloadFiles(fileIds: string[], zipName: string): Promise<void> {
  const res = await fetch("/api/files/batch-download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fileIds, zipName }),
    credentials: "include",
  });
  if (!res.ok) {
    throw new Error(`Batch download failed: ${res.status}`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = zipName.endsWith(".zip") ? zipName : `${zipName}.zip`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
