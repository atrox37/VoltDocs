import { del, get, patch, post, uploadFile } from "./client";

export interface GlossaryTerm {
  id: string;
  sourceLang: string;
  targetLang: string;
  sourceTerm: string;
  targetTerm: string;
  domain?: string;
  context?: string;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface AuditLog {
  id: string;
  termId?: string;
  action: string;
  before?: string;
  after?: string;
  actor: string;
  createdAt: string;
}

export interface GlossaryImportPreviewRow {
  sourceLang: string;
  targetLang: string;
  sourceTerm: string;
  targetTerm: string;
  context?: string;
  action: "create" | "replace" | "skip";
  existingId?: string;
  existingTargetTerm?: string;
  existingContext?: string;
}

export interface GlossaryImportPreviewResult {
  summary: {
    total: number;
    create: number;
    replace: number;
    skip: number;
  };
  rows: GlossaryImportPreviewRow[];
}

export function listTerms(params?: { q?: string }) {
  const query = new URLSearchParams();
  if (params?.q) query.set("q", params.q);
  const qs = query.toString();
  return get<{ terms: GlossaryTerm[] }>(`/glossary${qs ? `?${qs}` : ""}`);
}

export function createTerm(input: {
  sourceTerm: string;
  targetTerm: string;
  enabled?: boolean;
  sourceLang?: string;
  targetLang?: string;
}) {
  return post<{ id: string }>("/glossary/terms", input);
}

export function updateTerm(
  termId: string,
  input: {
    targetTerm?: string;
    context?: string;
    enabled?: boolean;
  }
) {
  return patch<{ ok: boolean }>(`/glossary/terms/${termId}`, input);
}

export function deleteTerm(termId: string) {
  return del<{ ok: boolean }>(`/glossary/terms/${termId}`);
}

export function getAuditLogs() {
  return get<{ logs: AuditLog[] }>("/glossary/audit-logs");
}

export function previewGlossaryImport(file: File) {
  return uploadFile<GlossaryImportPreviewResult>("/glossary/import/preview", file);
}

export function commitGlossaryImport(rows: GlossaryImportPreviewRow[]) {
  return post<{ ok: boolean; summary: { create: number; replace: number; skip: number } }>(
    "/glossary/import/commit",
    { rows }
  );
}

export function getTermHitCounts() {
  return get<{ hitCounts: Record<string, number> }>("/glossary/hit-counts");
}
