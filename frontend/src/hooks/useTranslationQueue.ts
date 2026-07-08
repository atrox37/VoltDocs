import { useEffect, useRef, useState } from "react";
import { Upload } from "antd";
import type { RcFile } from "antd/es/upload";
import type { MessageInstance } from "antd/es/message/interface";
import {
  batchDownloadFiles,
  createTranslationJob,
  exportTranslation,
  getJobProgress,
  getTranslationJob,
  type TranslationJob,
  type TranslationSegment,
} from "@/api/translation";

export type FileStatus = "pending" | "uploading" | "translating" | "done" | "failed";
export type SegmentReview = Record<string, string>;
export type ConfirmedReview = Record<string, boolean>;

export interface FileEntry {
  uid: string;
  file: File;
  status: FileStatus;
  progress: number;
  jobId?: string;
  job?: TranslationJob;
  errorMessage?: string;
  outputFileId?: string;
  outputFileName?: string;
  reviewing: boolean;
  edits: SegmentReview;
  confirmed: ConfirmedReview;
  segments: TranslationSegment[];
  segmentsLoaded: boolean;
}

interface UseTranslationQueueOptions {
  message: MessageInstance;
  sourceLang: string;
  targetLang: string;
}

const SUPPORTED_EXTENSIONS = new Set(["docx", "xlsx", "md", "markdown"]);

function createEntry(file: RcFile): FileEntry {
  return {
    uid: file.uid,
    file,
    status: "pending",
    progress: 0,
    reviewing: false,
    edits: {},
    confirmed: {},
    segments: [],
    segmentsLoaded: false,
  };
}

export function useTranslationQueue({
  message,
  sourceLang,
  targetLang,
}: UseTranslationQueueOptions) {
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const pollTimers = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  useEffect(() => {
    return () => {
      for (const timer of Object.values(pollTimers.current)) {
        clearInterval(timer);
      }
      pollTimers.current = {};
    };
  }, []);

  const updateEntry = (uid: string, patch: Partial<FileEntry>) => {
    setEntries((prev) => prev.map((entry) => (entry.uid === uid ? { ...entry, ...patch } : entry)));
  };

  const clearPollTimer = (uid: string) => {
    const timer = pollTimers.current[uid];
    if (timer) {
      clearInterval(timer);
      delete pollTimers.current[uid];
    }
  };

  const handleBeforeUpload = (file: RcFile) => {
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (!ext || !SUPPORTED_EXTENSIONS.has(ext)) {
      message.warning(`${file.name} 不受支持，请上传 .docx、.xlsx 或 .md 文件。`);
      return Upload.LIST_IGNORE;
    }
    setEntries((prev) => [...prev, createEntry(file)]);
    return false;
  };

  const removeEntry = (uid: string) => {
    clearPollTimer(uid);
    setEntries((prev) => prev.filter((entry) => entry.uid !== uid));
  };

  const loadReviewSegments = async (uid: string) => {
    const entry = entries.find((item) => item.uid === uid);
    if (!entry?.jobId) {
      return;
    }
    if (entry.segmentsLoaded) {
      updateEntry(uid, { reviewing: true });
      return;
    }

    const { segments } = await getTranslationJob(entry.jobId);
    updateEntry(uid, { segments, segmentsLoaded: true, reviewing: true });
  };

  const startPollingJob = (uid: string, jobId: string) => {
    const timer = setInterval(async () => {
      try {
        const { status, progress } = await getJobProgress(jobId);
        updateEntry(uid, { progress });
        if (status === "succeeded") {
          clearPollTimer(uid);
          const { job } = await getTranslationJob(jobId);
          updateEntry(uid, {
            status: "done",
            progress: 100,
            job,
            outputFileId: job.result?.autoFileId,
            outputFileName: job.result?.autoFileName,
          });
        } else if (status === "failed") {
          clearPollTimer(uid);
          try {
            const { job } = await getTranslationJob(jobId);
            updateEntry(uid, {
              status: "failed",
              progress: 0,
              errorMessage: job.errorMessage || undefined,
            });
          } catch {
            updateEntry(uid, { status: "failed", progress: 0 });
          }
        }
      } catch {
        // Keep polling until the backend job reaches a terminal state.
      }
    }, 1500);

    pollTimers.current[uid] = timer;
  };

  const startAll = async () => {
    const pendingEntries = entries.filter((entry) => entry.status === "pending");
    if (!pendingEntries.length || sourceLang === targetLang) {
      return;
    }

    await Promise.all(
      pendingEntries.map(async (entry) => {
        updateEntry(entry.uid, { status: "uploading", progress: 0 });
        try {
          const { id: jobId } = await createTranslationJob(entry.file, sourceLang, targetLang);
          updateEntry(entry.uid, { status: "translating", jobId, progress: 5 });
          startPollingJob(entry.uid, jobId);
        } catch (err: unknown) {
          updateEntry(entry.uid, {
            status: "failed",
            errorMessage: err instanceof Error ? err.message : "提交翻译任务失败。",
          });
        }
      }),
    );
  };

  const downloadFile = (entry: FileEntry) => {
    if (!entry.outputFileId) {
      return;
    }
    const anchor = document.createElement("a");
    anchor.href = `/api/files/${entry.outputFileId}/download`;
    anchor.download = entry.outputFileName || entry.file.name;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  };

  const downloadAll = async () => {
    const ids = entries.filter((entry) => entry.outputFileId).map((entry) => entry.outputFileId!);
    if (!ids.length) {
      return;
    }
    try {
      await batchDownloadFiles(ids, "translated_files.zip");
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : "批量下载失败。");
    }
  };

  const exportReviewedTranslation = async (entry: FileEntry) => {
    if (!entry.jobId) {
      return null;
    }
    const segments = entry.segments.map((segment) => ({
      sourceText: segment.sourceText,
      translation: entry.edits[segment.id] ?? segment.draftTranslation,
    }));
    return exportTranslation(entry.jobId, segments);
  };

  return {
    entries,
    startAll,
    removeEntry,
    handleBeforeUpload,
    loadReviewSegments,
    downloadFile,
    downloadAll,
    updateEntry,
    exportReviewedTranslation,
  };
}
