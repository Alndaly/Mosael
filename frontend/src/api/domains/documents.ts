import type { components } from "@/api/generated/schema";
import { API_BASE, api, getAuthToken } from "@/api/transport";

/** 文档的一次解析(ADR 0031):谁解析的、成没成、切成几段、每段的标题和页面图。 */
export type AssetExtraction = components["schemas"]["AssetExtractionOut"];
export type ExtractionSections = components["schemas"]["ExtractionSectionsOut"];

export function listExtractions(assetId: string): Promise<AssetExtraction[]> {
  return api<AssetExtraction[]>(`/api/assets/${assetId}/extractions`);
}

/** (重新)解析一次。`providerId` 点名用哪一家;不给就按「设置 → 能力提供方 → 文档解析」的默认。 */
export function parseDocument(assetId: string, providerId?: string | null): Promise<AssetExtraction> {
  return api<AssetExtraction>(`/api/assets/${assetId}/extractions`, {
    method: "POST",
    body: JSON.stringify({ provider_id: providerId ?? null }),
  });
}

export function extractionSections(assetId: string, extractionId: string, first = 1, last?: number): Promise<ExtractionSections> {
  const range = `first=${first}${last ? `&last=${last}` : ""}`;
  return api<ExtractionSections>(`/api/assets/${assetId}/extractions/${extractionId}/sections?${range}`);
}

/** 解析目录里的一个文件(页面图 `pages/…`、插图 `images/…`),给 `<img>` 用 —— 带上令牌。 */
export function extractionFileUrl(assetId: string, extractionId: string, path: string): string {
  const token = getAuthToken();
  return `${API_BASE}/api/assets/${assetId}/extractions/${extractionId}/files/${path}${token ? `?token=${token}` : ""}`;
}

/** 把最新成功的那份解析存成一篇笔记(插图这时才进素材库)。 */
export function saveDocumentAsNote(assetId: string): Promise<{ note_id: string; title: string }> {
  return api<{ note_id: string; title: string }>(`/api/assets/${assetId}/note`, { method: "POST" });
}

export type DocumentText = components["schemas"]["DocumentTextOut"];

/** 画板上的文档格:解析出的全文和解析的状态(连进写作 / 生成格时喂的就是它)。 */
export function documentText(assetId: string): Promise<DocumentText> {
  return api<DocumentText>(`/api/assets/${assetId}/document/text`);
}
