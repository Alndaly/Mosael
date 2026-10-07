/**
 * 某个页面让回复里的一种写法能点 —— 工作台的「助手」:`#12`、`#12:5` 点了在画布上定位那个节点。`rewrite` 在渲染之前把那种
 * 写法换成链接(地址以 `MARKDOWN_REF` 开头),`render` 画那种链接(见 Markdown 的 AgentMarkdown);没有这一层的地方,回复照原样渲染。
 *
 * context 单独一个模块:只依赖 React 和类型(见 app/contextIdentity.test)。
 */
import React from "react";

export interface MarkdownRefs {
  rewrite: (markdown: string) => string;
  render: (target: string, children: React.ReactNode) => React.ReactNode;
}

export const MarkdownRefsContext = React.createContext<MarkdownRefs | null>(null);

/** 页面引用的链接地址前缀(落在页内锚点里:Streamdown 放行 `#` 开头的地址,别处的链接也不会撞上它)。 */
export const MARKDOWN_REF = "#mosael-ref:";
