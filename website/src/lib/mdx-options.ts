import type { compileMDX } from "next-mdx-remote/rsc";
import rehypePrettyCode, { type Options as PrettyCodeOptions } from "rehype-pretty-code";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";

/**
 * 全站 MDX 的编译选项 —— 文档正文和插件详情页(README)共用这一份,两边的表格、标题锚点、代码高亮
 * 不会各长各的。
 *
 * **代码高亮在构建期做**(Shiki,经 rehype-pretty-code):页面是静态生成的,高亮好的 HTML 直接出在
 * 产物里,浏览器不多下一行 JS。浅色 / 深色两套主题同时写进每个 token 的 CSS 变量,由 globals.css
 * 按 `.dark` 切换 —— 和站点其余部分跟同一个主题开关,不会出现页面是深色、代码块是白底的情况。
 */
const prettyCode: PrettyCodeOptions = {
  theme: { light: "github-light", dark: "github-dark" },
  // 底色交给站点自己的代码框样式(globals.css 的 `.docs-body pre`),不用主题自带的那块颜色。
  keepBackground: false,
  // 不写语言的代码块(命令输出、目录树)也走同一套框,只是不上色。
  defaultLang: "plaintext",
};

type MdxOptions = NonNullable<NonNullable<Parameters<typeof compileMDX>[0]["options"]>["mdxOptions"]>;

export const mdxOptions: MdxOptions = {
  // gfm:表格和删除线,文档里两样都在用。
  remarkPlugins: [remarkGfm],
  // 标题带 id,才能从别处链到某一节。
  rehypePlugins: [rehypeSlug, [rehypePrettyCode, prettyCode]],
};
