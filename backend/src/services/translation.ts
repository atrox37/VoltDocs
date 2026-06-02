import fs from "node:fs";
import JSZip from "jszip";
import { config } from "../config.js";
import { matchGlossaryTerms, type PromptGlossaryTerm } from "./glossaryMatcher.js";

export interface TranslationSegment {
  id: string;
  order: number;
  sourceText: string;
  draftTranslation: string;
  qaPass: boolean;
  qaReason: string | null;
}

function stripXml(value: string) {
  return value.replace(/<[^>]+>/g, "");
}

function decodeXml(value: string) {
  return value
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'");
}

function escapeXml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

export async function extractDocxSegments(filePath: string) {
  const zip = await JSZip.loadAsync(fs.readFileSync(filePath));
  const documentXml = await zip.file("word/document.xml")?.async("string");
  if (!documentXml) {
    throw new Error("无法读取 word/document.xml，文件可能损坏或不是标准 DOCX。");
  }

  const paragraphs = [...documentXml.matchAll(/<w:p[\s\S]*?<\/w:p>/g)];
  const segments: TranslationSegment[] = [];
  for (const match of paragraphs) {
    const texts = [...match[0].matchAll(/<w:t[^>]*>([\s\S]*?)<\/w:t>/g)].map((m) => decodeXml(stripXml(m[1])));
    const sourceText = texts.join("").trim();
    if (!sourceText) continue;
    segments.push({
      id: `seg-${segments.length + 1}`,
      order: segments.length + 1,
      sourceText,
      draftTranslation: "",
      qaPass: true,
      qaReason: null
    });
  }
  return segments;
}

function numberQa(source: string, target: string) {
  const pattern = /-?\d+(?:\.\d+)?/g;
  const sourceNumbers = source.match(pattern) ?? [];
  const targetNumbers = target.match(pattern) ?? [];
  const pass = JSON.stringify(sourceNumbers) === JSON.stringify(targetNumbers);
  return {
    pass,
    reason: pass ? null : `数字不一致：原文 ${sourceNumbers.join(", ")}，译文 ${targetNumbers.join(", ")}`
  };
}

async function callTranslationLambda(params: {
  sourceLang: string;
  targetLang: string;
  segments: TranslationSegment[];
  glossary: PromptGlossaryTerm[];
  bearerToken?: string;
}): Promise<Array<{ id: string; translation?: string; draftTranslation?: string }>> {
  if (!config.translationLambdaUrl) {
    return params.segments.map((segment) => ({
      id: segment.id,
      translation: `[${params.targetLang}] ${segment.sourceText}`
    }));
  }

  const response = await fetch(config.translationLambdaUrl.replace(/\/$/, "") + "/translate/batch", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(params.bearerToken ? { authorization: `Bearer ${params.bearerToken}` } : {})
    },
    body: JSON.stringify({
      sourceLang: params.sourceLang,
      targetLang: params.targetLang,
      glossary: params.glossary,
      segments: params.segments.map((segment) => ({ id: segment.id, text: segment.sourceText }))
    })
  });

  if (!response.ok) {
    throw new Error(`Translation service failed: ${response.status} ${await response.text()}`);
  }

  const body = (await response.json()) as {
    segments?: Array<{ id: string; translation?: string; draftTranslation?: string }>;
  };
  return body.segments ?? [];
}

export async function translateSegments(params: {
  sourceLang: string;
  targetLang: string;
  segments: TranslationSegment[];
  bearerToken?: string;
}) {
  const glossary = matchGlossaryTerms(
    params.sourceLang,
    params.targetLang,
    params.segments.map((segment) => segment.sourceText)
  );
  const results = await callTranslationLambda({ ...params, glossary });
  const byId = new Map(results.map((item) => [item.id, item.translation ?? item.draftTranslation ?? ""]));
  return params.segments.map((segment) => {
    const draftTranslation = byId.get(segment.id) || segment.sourceText;
    const qa = numberQa(segment.sourceText, draftTranslation);
    return {
      ...segment,
      draftTranslation,
      qaPass: qa.pass,
      qaReason: qa.reason
    };
  });
}

export async function exportDocx(params: {
  inputPath: string;
  outputPath: string;
  segments: Array<{ sourceText: string; translation: string }>;
}) {
  const input = fs.readFileSync(params.inputPath);
  const zip = await JSZip.loadAsync(input);
  const file = zip.file("word/document.xml");
  const documentXml = await file?.async("string");
  if (!documentXml) throw new Error("无法读取 word/document.xml。");

  const translations = new Map(params.segments.map((segment) => [segment.sourceText.trim(), segment.translation]));
  const nextXml = documentXml.replace(/<w:p[\s\S]*?<\/w:p>/g, (paragraph) => {
    const textMatches = [...paragraph.matchAll(/<w:t[^>]*>([\s\S]*?)<\/w:t>/g)];
    const sourceText = textMatches.map((m) => decodeXml(stripXml(m[1]))).join("").trim();
    const translation = translations.get(sourceText);
    if (!translation || textMatches.length === 0) return paragraph;

    let replaced = false;
    return paragraph.replace(/<w:t([^>]*)>([\s\S]*?)<\/w:t>/g, (_match, attrs) => {
      if (replaced) return `<w:t${attrs}></w:t>`;
      replaced = true;
      return `<w:t${attrs}>${escapeXml(translation)}</w:t>`;
    });
  });

  zip.file("word/document.xml", nextXml);
  const output = await zip.generateAsync({ type: "nodebuffer" });
  fs.writeFileSync(params.outputPath, output);
}
