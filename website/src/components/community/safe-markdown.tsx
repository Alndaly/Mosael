import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

/**
 * 渲染**用户写的** markdown:社区插件的 README、条目说明、分享画板里文档格的正文。
 *
 * 不走 MDX(next-mdx-remote):MDX 会执行 `{表达式}` 和 import,只能给仓库里自己写的文档用。
 * react-markdown 不认原始 HTML(`skipHtml`),链接与图片地址过它自带的 urlTransform(只放
 * http(s)、mailto、相对路径)。排版沿用文档正文那一套(`.docs-body`),不另写一份。
 */
export function SafeMarkdown({ source, className }: { source: string; className?: string }) {
  return (
    <div className={cn("docs-body", className)}>
      <Markdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer nofollow ugc">
              {children}
            </a>
          ),
          // oxlint-disable-next-line nextjs/no-img-element
          img: ({ src, alt }) => <img src={typeof src === "string" ? src : undefined} alt={alt ?? ""} loading="lazy" className="max-w-full rounded-lg" />,
        }}
      >
        {source}
      </Markdown>
    </div>
  );
}
