import { Children, isValidElement } from "react";
import Link from "next/link";
import { CircleAlert, Info, Lightbulb, OctagonAlert } from "lucide-react";

import { QrCards } from "@/components/qr-cards";
import { localePath, type Locale } from "@/i18n/config";
import { Shot } from "@/components/shot";
import { cn } from "@/lib/utils";

/**
 * 文档正文里能用的组件。
 *
 * 迁移自 Starlight 的两件:`<Aside>`(原来的 `:::note`)和 `<Steps>`。名字保持一致,
 * 免得对着旧文档改内容的人还要先学一套新写法。
 */

const ASIDE_KINDS = {
  note: { icon: Info, tone: "border-l-foreground/30" },
  tip: { icon: Lightbulb, tone: "border-l-foreground/30" },
  caution: { icon: CircleAlert, tone: "border-l-amber-500/60" },
  danger: { icon: OctagonAlert, tone: "border-l-destructive/60" },
} as const;

export function Aside({
  type = "note",
  title,
  children,
}: {
  type?: keyof typeof ASIDE_KINDS;
  title?: string;
  children: React.ReactNode;
}) {
  const { icon: Icon, tone } = ASIDE_KINDS[type] ?? ASIDE_KINDS.note;
  return (
    <aside className={cn("my-7 border-l-2 bg-muted/40 py-4 pr-5 pl-5", tone)}>
      {title && (
        <p className="m-0 mb-2 flex items-center gap-2 font-sans text-sm font-medium">
          <Icon className="size-4 shrink-0" aria-hidden />
          {title}
        </p>
      )}
      <div className="[&>*:first-child]:mt-0 [&>*:last-child]:mb-0">{children}</div>
    </aside>
  );
}

/**
 * 编号步骤。正文里写的是普通有序列表,这里只是把序号做成竖排的连贯一列 ——
 * 步骤之间那条线是"还没走完"的视觉提示,比纯数字更耐读。
 */
export function Steps({ children }: { children: React.ReactNode }) {
  return (
    <div className="[&_ol]:m-0 [&_ol]:list-none [&_ol]:p-0 [&_ol>li]:relative [&_ol>li]:mb-8 [&_ol>li]:border-l [&_ol>li]:border-border [&_ol>li]:pb-2 [&_ol>li]:pl-8 [&_ol>li:last-child]:mb-0 [&_ol>li:last-child]:border-transparent [&_ol>li]:before:absolute [&_ol>li]:before:-left-[13px] [&_ol>li]:before:flex [&_ol>li]:before:size-6 [&_ol>li]:before:items-center [&_ol>li]:before:justify-center [&_ol>li]:before:rounded-full [&_ol>li]:before:border [&_ol>li]:before:border-border [&_ol>li]:before:bg-background [&_ol>li]:before:font-sans [&_ol>li]:before:text-xs [&_ol>li]:before:text-muted-foreground [&_ol>li]:before:content-[counter(list-item)] [&_ol>li>*:first-child]:mt-0">
      {children}
    </div>
  );
}

/**
 * 带锚点的标题。
 *
 * id 是 rehype-slug 生成的,直接透传;悬停时右边浮出一个 `#`,点了就能把这一节的链接
 * 复制走 —— 长文档里"发给同事看第三节"是最常见的需求,而没有锚点时只能发整页。
 */
function anchored(Tag: "h2" | "h3") {
  function Heading({ id, children, ...props }: React.ComponentProps<"h2">) {
    return (
      <Tag id={id} className="group scroll-mt-24" {...props}>
        {children}
        {id && (
          <a
            href={`#${id}`}
            className="ml-3 align-middle font-mono text-[0.7em] text-flame no-underline opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
          >
            #
          </a>
        )}
      </Tag>
    );
  }
  Heading.displayName = `Anchored${Tag.toUpperCase()}`;
  return Heading;
}

/** markdown 的 `![]()` —— 渲染成和首页同一套边框圆角的配图。 */
function MdxImage({ src, alt }: React.ComponentProps<"img">) {
  return typeof src === "string" ? <Shot src={src} alt={alt ?? ""} className="my-7" /> : null;
}

/**
 * 独占一行的图片,markdown 会包进一个 `<p>` 里。而 {@link MdxImage} 渲染的是 `<figure>` ——
 * `<p>` 装不下块级元素,浏览器会就地把 `<p>` 截断,于是服务端和客户端的 DOM 对不上,
 * 报 hydration 错。这里把这种"只装了一张图的段落"拆掉。
 */
function MdxParagraph({ children, ...props }: React.ComponentProps<"p">) {
  const items = Children.toArray(children);
  const onlyImage = items.length === 1 && isValidElement(items[0]) && items[0].type === MdxImage;
  return onlyImage ? <>{children}</> : <p {...props}>{children}</p>;
}

/**
 * MDX → React 的映射。
 *
 * 站内链接换成 next/link(客户端跳转、预取),站外链接补 `target`/`rel`。
 */
export function mdxComponents(locale: Locale) {
  return {
  Aside,
  Steps,
  Shot,
  QrCards,
  img: MdxImage,
  p: MdxParagraph,
  h2: anchored("h2"),
  h3: anchored("h3"),
  /**
   * 站内链接**自动补语言前缀**。
   *
   * 正文里写 `/docs/guides/plugins` 是自然的写法 —— 让每篇文档手写 `/zh/…` 的话,
   * 同一篇文章的中英版本就得各写各的链接,而漏改的那一条不会报错,只是 404。
   * 锚点(`#x`)不动:它指的是本页。
   */
  a: ({ href = "", children, ...props }: React.ComponentProps<"a">) => {
    if (/^https?:/.test(href)) {
      return (
        <a href={href} target="_blank" rel="noreferrer" {...props}>
          {children}
        </a>
      );
    }
    const internal = href.startsWith("/") ? localePath(locale, href) : href;
    return (
      <Link href={internal} {...props}>
        {children}
      </Link>
    );
  },
  };
}
