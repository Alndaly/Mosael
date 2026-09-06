/** Only actual published GitHub releases are eligible for the public changelog. */
export type PublishedRelease = {
  tag: string;
  name: string;
  body: string;
  prerelease: boolean;
  publishedAt: string;
  url: string;
};

export function publishedReleases(value: unknown): PublishedRelease[] {
  if (!Array.isArray(value)) return [];
  const releases = new Map<string, PublishedRelease>();
  for (const raw of value) {
    if (!raw || typeof raw !== "object" || raw.draft !== false) continue;
    const tag = raw.tag_name;
    if (typeof tag !== "string" || !/^v\d+\.\d+\.\d+(?:-[\w.-]+)?$/.test(tag)) continue;
    if (typeof raw.published_at !== "string" || !Number.isFinite(Date.parse(raw.published_at))) continue;
    releases.set(tag, {
      tag, name: typeof raw.name === "string" ? raw.name : tag,
      body: typeof raw.body === "string" ? raw.body : "",
      prerelease: raw.prerelease === true || tag.includes("-"),
      publishedAt: raw.published_at,
      url: `https://github.com/Alndaly/Mosael/releases/tag/${encodeURIComponent(tag)}`,
    });
  }
  return [...releases.values()].sort((a, b) => Date.parse(b.publishedAt) - Date.parse(a.publishedAt));
}

/** Plain-text excerpts, never execute remote release notes as MDX/HTML. */
export function releaseHighlights(body: string): string[] {
  return body.split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !/^#|^<!--|^\*?\*?Full Changelog|^\[.*(?:变更|Changelog)/i.test(line))
    .map((line) => line.replace(/^[-*+]\s+/, "")
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      .replace(/\*\*|`/g, ""))
    .slice(0, 5)
    .map((line) => line.length > 260 ? `${line.slice(0, 257)}…` : line);
}
