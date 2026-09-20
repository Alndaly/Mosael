/** 正文里一条链接能不能点 —— 只认 http(s) 和站内的笔记修订,别的一律当普通文本。

答案要在**渲染**那一层给,而不是在造这些链接的地方:Markdown 正文可能来自模型、来自笔记、
来自任何以后接进来的东西,而 `javascript:` 那类链接只要渲染出去就是可点的。
*/
export type Citation = { href: string; title: string; label: string; kind: "web" | "note"; excerpt: string };
export function canonicalSourceUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  if (/^#\/notes\?note=[\w-]+&revision=\d+$/.test(value)) return value;
  try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null; } catch { return null; }
}
