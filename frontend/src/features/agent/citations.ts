import type { AgentTimelineItem } from "./ToolCalls";

export type Citation = { href: string; title: string; label: string; kind: "web" | "note"; excerpt: string };
export function canonicalSourceUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  if (/^#\/notes\?note=[\w-]+&revision=\d+$/.test(value)) return value;
  try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null; } catch { return null; }
}
function unwrap(value: unknown): unknown {
  if (typeof value === "string") { try { return unwrap(JSON.parse(value)); } catch { return null; } }
  if (!value || typeof value !== "object") return value;
  const r = value as Record<string, unknown>;
  const details = r.details as Record<string, unknown> | undefined;
  if (details && "data" in details) return unwrap(details.data);
  if ("result" in r && Object.keys(r).length === 1) return unwrap(r.result);
  if (Array.isArray(r.content)) { const part = r.content.find(x => x?.type === "text"); if (part) return unwrap(part.text); }
  return value;
}
/** Only structured results from successful source-reading tools earn a source badge.
 * Ordinary assistant-provided links remain ordinary links, never evidence badges. */
export function collectCitations(timeline: AgentTimelineItem[] = []): Map<string, Citation> {
  const found = new Map<string, Citation>();
  for (const item of timeline) {
    if (item.type !== "tool" && item.type !== "subtool") continue;
    const { name, status, result } = item.tool;
    if (status !== "done" || !["web_search", "fetch_url", "read_note"].includes(name)) continue;
    const data = unwrap(result);
    const rows = Array.isArray(data) ? data : data && typeof data === "object" && Array.isArray((data as Record<string, unknown>).results) ? (data as {results: unknown[]}).results : [data];
    for (const row of rows) {
      if (!row || typeof row !== "object") continue;
      const r = row as Record<string, unknown>;
      const href = canonicalSourceUrl(name === "read_note" ? r.citation_url : r.url);
      if (!href || (name === "read_note") !== href.startsWith("#/notes?")) continue;
      const title = String(r.title || (name === "read_note" ? "Note" : new URL(href).hostname));
      found.set(href, {href, title, label: name === "read_note" ? title : new URL(href).hostname.replace(/^www\./, ""), kind: name === "read_note" ? "note" : "web", excerpt: String(r.snippet || r.text || r.markdown || "").slice(0, 280)});
    }
  }
  return found;
}
