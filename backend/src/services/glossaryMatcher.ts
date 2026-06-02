import { config } from "../config.js";
import { getDb } from "../db/database.js";

export interface GlossaryTerm {
  id: string;
  source_lang: string;
  target_lang: string;
  source_term: string;
  target_term: string;
  domain: string | null;
  context: string | null;
  required: number;
  forbidden_terms_json: string;
  enabled: number;
  priority: number;
  updated_at: string;
}

export interface PromptGlossaryTerm {
  source: string;
  target: string;
  context?: string;
  required: boolean;
}

function escapeRegex(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function isAsciiLike(value: string) {
  return /^[\x00-\x7F]+$/.test(value);
}

function termMatches(sourceText: string, term: string) {
  if (!term.trim()) return false;
  if (isAsciiLike(term)) {
    const pattern = new RegExp(`(^|[^A-Za-z0-9_])${escapeRegex(term)}([^A-Za-z0-9_]|$)`, "i");
    return pattern.test(sourceText);
  }
  return sourceText.includes(term);
}

export function matchGlossaryTerms(sourceLang: string, targetLang: string, segments: string[]) {
  const sourceText = segments.join("\n");
  const rows = getDb()
    .prepare(
      `SELECT * FROM glossary_terms
       WHERE enabled = 1 AND source_lang = ? AND target_lang = ?`
    )
    .all(sourceLang, targetLang) as GlossaryTerm[];

  let promptChars = 0;
  const matched = rows
    .filter((row) => termMatches(sourceText, row.source_term))
    .sort((a, b) => {
      if (b.required !== a.required) return b.required - a.required;
      if (b.priority !== a.priority) return b.priority - a.priority;
      if (b.source_term.length !== a.source_term.length) return b.source_term.length - a.source_term.length;
      return b.updated_at.localeCompare(a.updated_at);
    })
    .slice(0, config.glossaryMaxTerms)
    .filter((row) => {
      const nextChars = promptChars + row.source_term.length + row.target_term.length + (row.context?.length ?? 0);
      if (nextChars > config.glossaryMaxPromptChars) return false;
      promptChars = nextChars;
      return true;
    });

  return matched.map<PromptGlossaryTerm>((row) => ({
    source: row.source_term,
    target: row.target_term,
    context: row.context ?? undefined,
    required: row.required === 1
  }));
}

