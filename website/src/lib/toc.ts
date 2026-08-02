import GithubSlugger from "github-slugger";

/**
 * 从 MDX 源码里抽出本页目录。
 *
 * **用 github-slugger 而不是自己写一个** —— 正文里的 id 是 rehype-slug 生成的,而它内部用的
 * 就是这个包。自己实现一套"差不多"的规则,中文标题、连号、重名标题这三处迟早对不上,
 * 于是目录点了跳不动,还很难查。
 *
 * 只认 `##` 和 `###`:`#` 是页面标题(在 frontmatter 里),`####` 往下太细,列进目录只会
 * 把这一栏撑成第二篇正文。
 */
export type TocEntry = { depth: 2 | 3; text: string; id: string };

const FENCE = /^ {0,3}(`{3,}|~{3,})/;
const HEADING = /^(#{2,3})\s+(.+?)\s*#*$/;

export function tableOfContents(markdown: string): TocEntry[] {
  const slugger = new GithubSlugger();
  const entries: TocEntry[] = [];
  let fence: string | null = null;

  for (const line of markdown.split("\n")) {
    const fenceMatch = FENCE.exec(line);
    if (fenceMatch) {
      // 围栏内的 `# 注释` 不是标题。开着的围栏只被同种记号关掉。
      if (fence && fenceMatch[1][0] === fence[0]) fence = null;
      else if (!fence) fence = fenceMatch[1];
      continue;
    }
    if (fence) continue;

    const match = HEADING.exec(line);
    if (!match) continue;
    // 去掉标题里的行内标记(**粗体**、`代码`、[链接](…)),目录里只留字面。
    const text = match[2]
      .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/[*_`]/g, "")
      .trim();
    if (!text) continue;
    entries.push({ depth: match[1].length as 2 | 3, text, id: slugger.slug(text) });
  }

  return entries;
}
