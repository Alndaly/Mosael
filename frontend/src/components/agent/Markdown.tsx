import React from "react";
import { CodeBlock, CodeBlockCopyButton, Streamdown, type Components } from "streamdown";

import { WrapText } from "lucide-react";

import { codeHighlighter } from "@/components/agent/codeHighlighter";
import { cn } from "@/lib/utils";

import { useI18n } from "@/app/preferences";

/** 围栏代码块里的原始文本:markdown 把 ```…``` 渲染成 <pre><code>纯文本</code></pre>。 */
function codeText(node: React.ReactNode): string {
  if (typeof node === "string") return node;
  if (Array.isArray(node)) return node.map(codeText).join("");
  if (React.isValidElement<{ children?: React.ReactNode }>(node)) return codeText(node.props.children);
  return "";
}

/** ```ts 里的 ts —— 挂在内层 <code> 的 `language-*` class 上。 */
function codeLanguage(node: React.ReactNode): string {
  const child = React.Children.toArray(node).find((item) => React.isValidElement(item));
  const className = React.isValidElement<{ className?: string }>(child) ? child.props.className : undefined;
  return /(?:^|\s)language-([\w+#.-]+)/.exec(className ?? "")?.[1] ?? "";
}

/**
 * 代码卡:**一个框**,外加一行头部。
 *
 * 接管 `pre`,但**里面渲染 Streamdown 自己的 `CodeBlock`** —— 高亮仍归它(它从上下文里拿
 * 我们喂的高亮器),我们只换外壳。此前那版接管把内容当纯文本渲染,于是装上高亮器也不出颜色;
 * 而完全不接管又会得到 Streamdown 的三层结构:外框 + 一条 -mt-10 拉上来的 sticky 按钮带 +
 * 内框,两层同色边框套着,复制按钮浮在代码上像第二个框。
 *
 * 头部里放语言、换行开关、复制。换行开关是必要的:一行长 URL 或长正则不换行就只能横着拖,
 * 而拖的时候左边的行号会跟着滚走 —— 所以不换行时行号 sticky 在左侧。
 */
/**
 * 代码块头部那两颗图标按钮的样子。**两个按钮共用一份** —— 一个是本文件里手写的换行开关,
 * 另一个是 Streamdown 的 `CodeBlockCopyButton`,它们在界面上是同一种东西。
 *
 * `inline-grid place-items-center` 不是装饰:复制按钮渲染出来是 `display: block`,
 * 而 `p-0` 又把它自带的内边距抹掉了 —— 于是那个 14px 图标贴着 20px 方框的左边缘,右边空
 * 6px(真机实测的偏差就是 -6)。换行开关一直是对的,因为它自己写了 grid 居中;两边各写各的,
 * 才让这个差别一直没人发现。
 */
const HEADER_ICON_BUTTON =
  "inline-grid size-5 cursor-pointer place-items-center rounded-sm border-0 bg-transparent p-0 " +
  "text-muted-foreground hover:bg-secondary hover:text-foreground [&_svg]:size-3.5";

function CodeCard({ children }: React.ComponentProps<"pre"> & { node?: unknown }) {
  const t = useI18n();
  const [wrap, setWrap] = React.useState(false);
  const code = codeText(children).replace(/\n+$/, "");
  const language = codeLanguage(children);
  return (
    <div
      className={cn(
        "group my-2.5 overflow-hidden rounded-md border border-border bg-panel-inset",
        // CodeBlock 自带一层容器(rounded-xl + border + p-2)和它自己的语言标签行 ——
        // `className` 只落到它的内层代码区,够不着这两个。在这儿把它们剥掉:框和标签由我们出,
        // 它只负责高亮后的代码体。否则就是两个框、两个 "python"(真机截图)。
        "[&>div:last-child]:!my-0 [&>div:last-child]:!gap-0 [&>div:last-child]:!rounded-none",
        "[&>div:last-child]:!border-0 [&>div:last-child]:!bg-transparent [&>div:last-child]:!p-0",
        "[&>div:last-child>div:first-child]:!hidden",
      )}
    >
      <div className="flex h-7 items-center gap-1 border-b border-border px-2.5 text-ui-2xs text-muted-foreground">
        <span className="font-mono lowercase">{language}</span>
        <span className="ml-auto flex items-center gap-1.5">
          <button
            type="button"
            className={HEADER_ICON_BUTTON}
            title={wrap ? t("codeNoWrap") : t("codeWrap")}
            aria-label={wrap ? t("codeNoWrap") : t("codeWrap")}
            aria-pressed={wrap}
            onClick={() => setWrap((value) => !value)}
          >
            <WrapText size={14} />
          </button>
          <CodeBlockCopyButton className={HEADER_ICON_BUTTON} code={code} />
        </span>
      </div>
      <CodeBlock
        code={code}
        language={language}
        className={cn(
          // 框由外面那层给,这里只留内容。
          // **横向内边距为 0**:滚动容器一旦有 px,`left-0` 贴的是内边距的外沿,左边就漏出
          // 一条缝让代码从行号旁边透出来(真机截图),而且刚一拖动行号会先跟着挪一小段。
          // 留白改由行号自己和行尾给。
          "!m-0 !rounded-none !border-0 !bg-transparent !px-0 !py-2 !text-ui-xs",
          // **行号钉在左边**:它是每行的 ::before 计数器,默认跟着内容一起横向滚走 ——
          // 横着拖两屏之后就没有行号可看了。sticky + 一层不透明底,代码从它下面滑过去;
          // box-content 让 padding 加在 w-6 之外,这样底色能盖满整条行号槽。
          "[&_code>span]:before:sticky [&_code>span]:before:left-0 [&_code>span]:before:z-10",
          "[&_code>span]:before:box-content [&_code>span]:before:bg-panel-inset",
          "[&_code>span]:before:pl-2.5 [&_code>span]:before:pr-2 [&_code>span]:pr-2.5",
          wrap && "[&_pre]:whitespace-pre-wrap [&_pre]:[overflow-wrap:anywhere]",
        )}
      />
    </div>
  );
}

/** 定值:组件表每次换新对象都会让 Streamdown 重建一遍内部的 components。 */
const COMPONENTS: Components = { pre: CodeCard };

export function AgentMarkdown({ children }: { children: string }) {
  const t = useI18n();
  return (
    <Streamdown
      className="min-w-0 max-w-full [&_:is(p,ul,ol,table)]:mx-0 [&_:is(p,ul,ol,table)]:mt-0 [&_:is(p,ul,ol,table)]:mb-2.5 [&_:is(p,ul,ol,table):last-child]:mb-0 [&_:is(h1,h2)]:mt-4 [&_:is(h1,h2)]:mb-2 [&_:is(h1,h2)]:text-[15px] [&_:is(h1,h2)]:font-[650] [&_:is(h1,h2)]:tracking-[-0.01em] [&_:is(h3,h4)]:mt-3 [&_:is(h3,h4)]:mb-1.5 [&_:is(h3,h4)]:text-ui-md [&_:is(h3,h4)]:font-[650] [&_:is(h1,h2,h3,h4):first-child]:mt-0 [&_table]:w-full [&_table]:border-collapse [&_table]:text-ui-sm [&_:is(th,td)]:border [&_:is(th,td)]:border-border [&_:is(th,td)]:px-2 [&_:is(th,td)]:py-1.5 [&_:is(th,td)]:text-left [&_th]:bg-secondary [&_th]:font-semibold [&_code]:rounded-sm [&_code]:bg-panel-inset [&_code]:px-1 [&_code]:py-px [&_code]:font-mono [&_code]:text-xs [&_pre_code]:rounded-none [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_pre_code]:text-[inherit] [&_:is(ul,ol)]:pl-[18px] [&_div:has(>div>table)]:my-2.5 [&_div:has(>div>table)]:rounded-none [&_div:has(>div>table)]:border-0 [&_div:has(>div>table)]:bg-transparent [&_div:has(>div>table)]:p-0 [&_div:has(>table)]:rounded-none [&_div:has(>table)]:border-0 [&_div:has(>table)]:bg-transparent"
      components={COMPONENTS}
      plugins={{ code: codeHighlighter }}
      controls={{ table: false, code: { copy: true, download: false } }}
      translations={{ copyCode: t("copy"), copied: t("copied") }}
    >
      {children}
    </Streamdown>
  );
}
