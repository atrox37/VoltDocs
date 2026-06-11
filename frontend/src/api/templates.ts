import { get, patch, del, uploadFile } from "./client";

export interface Template {
  id: string;
  fileId: string;
  fileName: string;
  language?: string;
  tags: string; // JSON array string
  uploadedBy: string;
  createdAt: string;
  updatedAt: string;
}

export function listTemplates() {
  return get<{ templates: Template[] }>("/templates");
}

export function uploadTemplate(file: File, language?: string, tags?: string) {
  const fields: Record<string, string> = {};
  if (language) fields.language = language;
  if (tags) fields.tags = tags;
  return uploadFile<{ id: string; fileId: string; fileName: string }>("/templates", file, fields);
}

export function updateTemplate(templateId: string, input: { language?: string; tags?: string[] }) {
  return patch<{ ok: boolean }>(`/templates/${templateId}`, input);
}

export function deleteTemplate(templateId: string) {
  return del<{ ok: boolean }>(`/templates/${templateId}`);
}

export function getDownloadUrl(fileId: string) {
  return `/api/files/${fileId}/download`;
}
