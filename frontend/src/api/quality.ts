import { get } from "./client";

export interface QualityFilters {
  dateFrom?: string;
  dateTo?: string;
  fileType?: string;
  sourceLang?: string;
  targetLang?: string;
  userEmail?: string;
}

export interface QualityFilterOptions {
  users: string[];
  fileTypes: string[];
  languagePairs: Array<{
    sourceLang: string;
    targetLang: string;
  }>;
}

export interface QualitySummaryResponse {
  filters: QualityFilterOptions;
  summary: {
    jobTotal: number;
    segmentTotal: number;
    qaFailedSegments: number;
    qaFailureRate: number;
    tmHits: number;
    tmInserted: number;
    tmUpdated: number;
    tmSkipped: number;
    tmPruned: number;
    tmRecordTotal: number;
    tmRiskyTotal: number;
    tmHumanConfirmedTotal: number;
  };
}

export interface KeyCountItem {
  key: string;
  count: number;
}

export interface QualityQaResponse {
  failureTypes: KeyCountItem[];
  rules: KeyCountItem[];
  fileTypes: KeyCountItem[];
  users: KeyCountItem[];
  trend: Array<{
    date: string;
    count: number;
  }>;
}

export interface QualityTmResponse {
  qualityTiers: KeyCountItem[];
  scopeFamilies: KeyCountItem[];
  trend: Array<{
    date: string;
    hits: number;
    inserted: number;
    updated: number;
    skipped: number;
    pruned: number;
  }>;
  topHits: Array<{
    sourceText: string;
    targetText: string;
    scope: string;
    scopeFamily: string;
    qualityTier: string;
    hitCount: number;
  }>;
}

export interface QualityIssueItem {
  jobId: string;
  segmentId: string;
  segmentOrder: number;
  fileName: string;
  fileType: string;
  userEmail: string;
  sourceLang: string;
  targetLang: string;
  sourceText: string;
  draftTranslation: string;
  qaPass: boolean;
  qaReason?: string | null;
  qaRuleName?: string | null;
  qaFailureType?: string | null;
  fromCache: boolean;
  tmQuality: number;
  createdAt: string;
  finishedAt?: string | null;
}

export interface QualityIssuesResponse {
  items: QualityIssueItem[];
  pagination: {
    page: number;
    pageSize: number;
    total: number;
  };
}

function buildQuery(params: Record<string, string | number | boolean | undefined>) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === "" || value === null) {
      return;
    }
    search.set(key, String(value));
  });
  const query = search.toString();
  return query ? `?${query}` : "";
}

export function getQualitySummary(filters: QualityFilters) {
  return get<QualitySummaryResponse>(`/admin/quality/summary${buildQuery(filters)}`);
}

export function getQualityQa(filters: QualityFilters) {
  return get<QualityQaResponse>(`/admin/quality/qa${buildQuery(filters)}`);
}

export function getQualityTm(filters: QualityFilters) {
  return get<QualityTmResponse>(`/admin/quality/tm${buildQuery(filters)}`);
}

export function getQualityIssues(
  filters: QualityFilters & { failedOnly?: boolean; page?: number; pageSize?: number },
) {
  return get<QualityIssuesResponse>(`/admin/quality/issues${buildQuery(filters)}`);
}
