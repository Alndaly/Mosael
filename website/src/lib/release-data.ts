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

/** 更新日志每条要点最多显示多少个字(按看得见的字数,截断交给 InlineMarkdown)。 */
export const HIGHLIGHT_MAX_LENGTH = 260;

/**
 * 从 GitHub 发布说明里摘前几条要点。
 *
 * 摘出来的仍是**行内 markdown**(`**粗体**`、`` `代码` ``、链接),由页面交给 InlineMarkdown
 * 渲染 —— 远端内容永远不当 MDX/HTML 执行,也不在这里另写一套正则去剥记号。这里只去掉
 * 行首的列表符号、跳过标题和「Full Changelog」那类行。
 */
export function releaseHighlights(body: string): string[] {
  return body.split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !/^#|^<!--|^\*?\*?Full Changelog|^\[.*(?:变更|Changelog)/i.test(line))
    .map((line) => line.replace(/^[-*+]\s+/, ""))
    .slice(0, 5);
}
