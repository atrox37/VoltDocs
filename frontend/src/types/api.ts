export interface Job {
  id: string;
  user_id: string;
  type: "convert" | "translation";
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress: number;
  input_file_id: string;
  output_file_id: string | null;
  result_json: string | null;
  error_message: string | null;
}

export interface TranslationSegment {
  id: string;
  order: number;
  sourceText: string;
  draftTranslation: string;
  qaPass: boolean;
  qaReason: string | null;
}

