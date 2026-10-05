import { SITE } from "@/lib/site";

/**
 * 插件 README → 插件详情页拿去编译的 MDX 正文。详情页(`app/[locale]/plugins/[slug]`)和守着它的测试
 * (test/plugin-docs.test.mjs:每份 README 都按这一套编一遍)用的是同一个函数 —— 测试编得过,构建就编得过。
 */
export function pluginDocSource(markdown: string, source: string): string {
  return rewriteRelativeLinks(unwrapAutolinks(dropLeadingTitle(markdown)), source);
}

/**
 * `<https://…>` 是合法的 markdown(autolink),但 **MDX 会把它当成 JSX 标签**,直接编译失败。
 *
 * README 是给人写的、也要在 GitHub 上好看,不该为了我们的渲染器改写法 —— 所以在这里
 * 转成普通链接。这不是"容错",是两种方言之间的翻译:markdown 认 autolink,MDX 不认。
 */
function unwrapAutolinks(markdown: string): string {
  return markdown.replace(/<(https?:\/\/[^\s>]+)>/g, "[$1]($1)");
}

/**
 * README 开头那行 `# 插件名` 在 GitHub 上是标题,在这里和页头的名字重复 —— 页头已经说了
 * 这是谁,正文从第一段说明开始。
 */
function dropLeadingTitle(markdown: string): string {
  return markdown.replace(/^\s*#\s+[^\n]*\n+/, "");
}

/**
 * README 里的相对链接**在网页上是坏的**。
 *
 * 那些路径是按仓库目录写的(`../../../docs/PLUGIN_MANIFEST.md`),在 GitHub 上点得开,
 * 搬到 /plugins/<slug> 这个地址下就指向了不存在的地方。渲染前统一改指回仓库 ——
 * 不改的话,详情页上每一个「见 xxx」都是 404,而写 README 的人完全不知情。
 */
function rewriteRelativeLinks(markdown: string, source: string): string {
  return markdown.replace(/\]\((?!https?:\/\/|#)([^)]+)\)/g, (match, target: string) => {
    const cleaned = String(target).trim();
    if (cleaned.startsWith("/")) return match;
    const resolved = new URL(cleaned, `https://x/${source}/`).pathname.replace(/^\//, "");
    return `](${SITE.repo}/blob/main/${resolved})`;
  });
}
