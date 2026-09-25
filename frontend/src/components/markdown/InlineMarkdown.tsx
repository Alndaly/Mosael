import React from "react";

import { canonicalSourceUrl } from "./links";
import { parseInline, type InlineNode } from "./inlineSyntax";

/** 粗体和代码**不定文字颜色**,跟着所在那一行走:同一段说明会出现在灰字副标题、提示气泡、确认卡标题里。 */
function render(nodes: InlineNode[], links: boolean): React.ReactNode[] {
  return nodes.map((node, key) => {
    switch (node.type) {
      case "text":
        return node.value;
      case "code":
        return (
          <code key={key} className="rounded-sm bg-panel-inset px-1 py-px font-mono text-[0.92em] [overflow-wrap:anywhere]">
            {node.value}
          </code>
        );
      case "break":
        return <br key={key} />;
      case "strong":
        return (
          <strong key={key} className="font-semibold">
            {render(node.children, links)}
          </strong>
        );
      case "emphasis":
        return <em key={key}>{render(node.children, links)}</em>;
      case "delete":
        return <del key={key}>{render(node.children, links)}</del>;
      case "link": {
        // 与 AgentMarkdown 同一条规则(links.ts):只认 http(s),`javascript:` 之类只留文字。
        const href = links ? canonicalSourceUrl(node.href) : null;
        const children = render(node.children, links);
        if (!href) return <React.Fragment key={key}>{children}</React.Fragment>;
        return (
          <a key={key} href={href} target="_blank" rel="noopener noreferrer" className="break-words text-primary underline underline-offset-2">
            {children}
          </a>
        );
      }
    }
  });
}

/**
 * 把一行数据里的行内 markdown 渲染出来(规则见 ./inlineSyntax.ts)。只出行内元素,
 * 放进 `<small>`、`<span>`、`<p>`、`<button>` 都合法。
 *
 * `links={false}`:放在按钮、整块可点的行、提示气泡里时用 —— 按钮里套链接是无效的交互嵌套,
 * 气泡里的链接也点不到。
 */
export function InlineMarkdown({ text, links = true }: { text: string; links?: boolean }) {
  const nodes = React.useMemo(() => parseInline(text), [text]);
  return <>{render(nodes, links)}</>;
}
