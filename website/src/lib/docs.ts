import fs from "node:fs";
import path from "node:path";

import type { Locale } from "@/i18n/config";

/**
 * 文档内容层。
 *
 * 正文是 `content/docs/<locale>/<section>/<slug>.mdx` 里的文件,不进数据库也不过 CMS ——
 * 文档跟着代码走,同一个 PR 里改实现和改说明,评审时能看见它们对不对得上。
 *
 * frontmatter 只有 title / description / order 三个标量,所以这里手写解析而不是拉一个
 * YAML 依赖:字段一旦长出嵌套结构,该做的是换掉这段而不是往里加分支。
 */
export const DOC_SECTIONS = ["start", "guides", "about"] as const;

export type DocSection = (typeof DOC_SECTIONS)[number];

export type DocMeta = {
  section: DocSection;
  /** 文件名,也是 URL 的最后一段。 */
  name: string;
  /** 侧边栏内的排序,来自 frontmatter。 */
  order: number;
  title: string;
  description: string;
};

export type Doc = DocMeta & { body: string };

const CONTENT_ROOT = path.join(process.cwd(), "content", "docs");

function parseFrontmatter(raw: string): {
  data: Record<string, string>;
  body: string;
} {
  const match = /^---\n([\s\S]*?)\n---\n?/.exec(raw);
  if (!match) return { data: {}, body: raw };
  const data: Record<string, string> = {};
  for (const line of match[1].split("\n")) {
    const at = line.indexOf(":");
    if (at > 0) data[line.slice(0, at).trim()] = line.slice(at + 1).trim();
  }
  return { data, body: raw.slice(match[0].length) };
}

function readMeta(locale: Locale, section: DocSection, file: string): DocMeta {
  const raw = fs.readFileSync(path.join(CONTENT_ROOT, locale, section, file), "utf8");
  const { data } = parseFrontmatter(raw);
  return {
    section,
    name: file.replace(/\.mdx$/, ""),
    order: Number(data.order ?? 99),
    title: data.title ?? file,
    description: data.description ?? "",
  };
}

/** 某个语言下的全部文档,按 section 顺序 + frontmatter 的 order 排好。 */
export function listDocs(locale: Locale): DocMeta[] {
  return DOC_SECTIONS.flatMap((section) => {
    const dir = path.join(CONTENT_ROOT, locale, section);
    if (!fs.existsSync(dir)) return [];
    return fs
      .readdirSync(dir)
      .filter((file) => file.endsWith(".mdx"))
      .map((file) => readMeta(locale, section, file))
      .sort((a, b) => a.order - b.order);
  });
}

export function readDoc(locale: Locale, section: string, name: string): Doc | null {
  if (!(DOC_SECTIONS as readonly string[]).includes(section)) return null;
  const file = path.join(CONTENT_ROOT, locale, section, `${name}.mdx`);
  if (!fs.existsSync(file)) return null;
  const { body } = parseFrontmatter(fs.readFileSync(file, "utf8"));
  return { ...readMeta(locale, section as DocSection, `${name}.mdx`), body };
}

/** 文档区的落地页 —— 侧边栏第一项,也是 `/docs` 直接跳过去的地方。 */
export function firstDoc(locale: Locale): DocMeta {
  const [first] = listDocs(locale);
  return first;
}

export function docHref(locale: Locale, doc: DocMeta): string {
  return `/${locale}/docs/${doc.section}/${doc.name}`;
}
