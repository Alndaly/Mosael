import GithubSlugger from "github-slugger";

import { DOC_SECTIONS, docHref, listDocs, readDoc } from "@/lib/docs";
import type { Locale } from "@/i18n/config";

/**
 * 搜索索引。
 *
 * **构建期把 24 页正文抽成一份 JSON**,运行时全在浏览器里匹配 —— 不需要后端,也就不需要
 * 部署一个服务才能搜。旧站的 Pagefind 是同一个思路。
 *
 * 每个小节(`##` / `###`)单独成一条:搜到的是"哪一页的哪一节",点进去直接落到那个锚点,
 * 而不是把人丢到一篇长文档的顶部再自己找。
 */
export type SearchEntry = {
  href: string;
  /** 页标题。 */
  title: string;
  /** 分区名(开始 / 使用指南 / 关于),结果列表里分组用。 */
  section: string;
  /** 小节标题;整页那条为空。 */
  heading: string;
  /** 用来匹配的正文,已经去掉 markdown 记号。 */
  body: string;
};

const FENCE = /^ {0,3}(`{3,}|~{3,})/;
const HEADING = /^(#{2,3})\s+(.+?)\s*#*$/;

/** 去掉 markdown 与 MDX 的记号,只留人读的字 —— 索引里留着 `**` 和 `<Aside>` 只会干扰匹配。 */
function plain(text: string): string {
  return text
    .replace(/<[^>]+>/g, " ")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[*_`>|#-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function buildSearchIndex(locale: Locale, sectionLabels: Record<string, string>): SearchEntry[] {
  const entries: SearchEntry[] = [];

  for (const meta of listDocs(locale)) {
    const doc = readDoc(locale, meta.section, meta.name);
    if (!doc) continue;
    const href = docHref(locale, meta);
    const section = sectionLabels[meta.section] ?? meta.section;

    // 整页一条:标题和摘要能命中,即使正文里没出现那个词。
    const page: SearchEntry = { href, title: doc.title, section, heading: "", body: plain(doc.description) };
    entries.push(page);

    // **每篇一个 slugger**,和 rehype-slug 的行为一致:同名标题靠计数器区分(x、x-1、x-2)。
    // 用同一个包而不是自己写一套"差不多"的规则 —— 差一点点,搜索结果点进去就跳不动。
    const slugger = new GithubSlugger();
    let heading = "";
    let slug = "";
    let buffer: string[] = [];
    let fence: string | null = null;

    const flush = () => {
      const body = plain(buffer.join(" "));
      buffer = [];
      if (!heading) {
        // 第一个小节之前的开场白没有自己的锚点,并进整页那条 —— 否则结果里会出现两行
        // 标题一样、链接也一样的条目。
        if (body) page.body = `${page.body} ${body}`.trim();
        return;
      }
      entries.push({ href: slug ? `${href}#${slug}` : href, title: doc.title, section, heading, body });
    };

    for (const line of doc.body.split("\n")) {
      const fenceMatch = FENCE.exec(line);
      if (fenceMatch) {
        if (fence && fenceMatch[1][0] === fence[0]) fence = null;
        else if (!fence) fence = fenceMatch[1];
        continue;
      }
      // 代码块整段不进索引:搜「导出」不该被一段恰好含 export 的示例代码顶到前面。
      if (fence) continue;

      const match = HEADING.exec(line);
      if (match) {
        flush();
        heading = plain(match[2]);
        slug = slugger.slug(heading);
        continue;
      }
      buffer.push(line);
    }
    flush();
  }

  return entries;
}

export { DOC_SECTIONS };
