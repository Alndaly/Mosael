import React from "react";
import { CodeBlockCopyButton, Streamdown, type Components } from "streamdown";

import { useI18n } from "@/app/preferences";

/** 围栏代码块里的原始文本:react-markdown 把 ```…``` 渲染成 <pre><code>纯文本</code></pre>。 */
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
 * 代码卡:**一个框**。
 *
 * Streamdown 默认要三层框来装一段代码 —— 带边框底色的外卡、常驻浮在右上角的按钮组、
 * <pre> 自己那层边框。那套结构是为语法高亮准备的,而我们没装高亮插件(`plugins.codeHighlighter`),
 * 于是只剩下框。
 *
 * 所以直接接管 `pre`:自己画那一个框,横向滚动交给框里的 <pre>(边框和圆角因此不会被长行推走),
 * 语言标签和复制按钮浮在框内右上角、悬停才显现 —— 不看代码的时候它们不占视觉。
 *
 * 复用 `CodeBlockCopyButton` 而不是自己写一个:剪贴板、"已复制"的两秒回执、图标和文案
 * 都跟着 Streamdown 的上下文走。
 */
function CodeCard({ children }: React.ComponentProps<"pre"> & { node?: unknown }) {
  const code = codeText(children).replace(/\n+$/, "");
  const language = codeLanguage(children);
  return (
    <div className="group relative mt-0 mb-2.5 overflow-hidden rounded-md border border-border bg-panel-inset last:mb-0">
      {/* 悬停才显现。隐藏时 pointer-events-none,免得一个看不见的按钮挡住选中代码。 */}
      <div className="pointer-events-none absolute top-1 right-1 z-10 flex items-center gap-1 rounded-sm bg-panel-inset pl-2 opacity-0 transition-opacity duration-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100 group-hover:pointer-events-auto group-hover:opacity-100">
        {language && <span className="font-mono text-ui-2xs lowercase text-muted-foreground">{language}</span>}
        <CodeBlockCopyButton className="p-0.5 [&_svg]:size-3.5" code={code} />
      </div>
      <pre className="m-0 overflow-x-auto px-2.5 py-2 font-mono text-ui-xs leading-[1.55] text-foreground">
        <code>{code}</code>
      </pre>
    </div>
  );
}

/** 定值:组件表每次换新对象都会让 Streamdown 重建一遍内部的 components。 */
const COMPONENTS: Components = { pre: CodeCard };

/**
 * 智能体正文的 Markdown 渲染。
 *
 * 排版规则集中在这一串 className 里:块级元素统一 10px 下缝(末块清零),表格拍平成裸表格,
 * 行内 code 是小药丸、代码块里的 code 则完全交给 {@link CodeCard}。
 */
export function AgentMarkdown({ children }: { children: string }) {
  const t = useI18n();
  return (
    <Streamdown
      className="min-w-0 max-w-full [&_:is(p,ul,ol,table)]:mx-0 [&_:is(p,ul,ol,table)]:mt-0 [&_:is(p,ul,ol,table)]:mb-2.5 [&_:is(p,ul,ol,table):last-child]:mb-0 [&_:is(h1,h2)]:mt-4 [&_:is(h1,h2)]:mb-2 [&_:is(h1,h2)]:text-[15px] [&_:is(h1,h2)]:font-[650] [&_:is(h1,h2)]:tracking-[-0.01em] [&_:is(h3,h4)]:mt-3 [&_:is(h3,h4)]:mb-1.5 [&_:is(h3,h4)]:text-ui-md [&_:is(h3,h4)]:font-[650] [&_:is(h1,h2,h3,h4):first-child]:mt-0 [&_table]:w-full [&_table]:border-collapse [&_table]:text-ui-sm [&_:is(th,td)]:border [&_:is(th,td)]:border-border [&_:is(th,td)]:px-2 [&_:is(th,td)]:py-1.5 [&_:is(th,td)]:text-left [&_th]:bg-secondary [&_th]:font-semibold [&_code]:rounded-sm [&_code]:bg-panel-inset [&_code]:px-1 [&_code]:py-px [&_code]:font-mono [&_code]:text-xs [&_pre_code]:rounded-none [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_pre_code]:text-[inherit] [&_:is(ul,ol)]:pl-[18px] [&_div:has(>div>table)]:my-2.5 [&_div:has(>div>table)]:rounded-none [&_div:has(>div>table)]:border-0 [&_div:has(>div>table)]:bg-transparent [&_div:has(>div>table)]:p-0 [&_div:has(>table)]:rounded-none [&_div:has(>table)]:border-0 [&_div:has(>table)]:bg-transparent"
      components={COMPONENTS}
      controls={{ table: false }}
      translations={{ copyCode: t("copy"), copied: t("copied") }}
    >
      {children}
    </Streamdown>
  );
}
