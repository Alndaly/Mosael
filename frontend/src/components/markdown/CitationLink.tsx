import React from "react";
import { BookOpen, Globe } from "lucide-react";
import { canonicalSourceUrl, type Citation } from "./links";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";

export const CitationContext = React.createContext<Map<string, Citation>>(new Map());
export function CitationLink({ href, children }: React.ComponentProps<"a"> & {node?: unknown}) {
  const sources = React.useContext(CitationContext);
  const normalized = canonicalSourceUrl(href);
  const source = normalized ? sources.get(normalized) : undefined;
  if (!source) {
    const safe = normalized || (href?.startsWith("#/") ? href : undefined);
    //: 没有结构化来源的普通链接也要能看见完整地址:气泡里只写了域名/短标题,悬停才回答"到底去哪"。
    return safe ? (
      <Hint label={safe}>
        <a href={safe} target={safe.startsWith("#") ? undefined : "_blank"} rel="noopener noreferrer" className="text-primary underline underline-offset-2 break-words">{children}</a>
      </Hint>
    ) : <span>{children}</span>;
  }
  const Icon = source.kind === "note" ? BookOpen : Globe;
  //: 网站 / 笔记引用和节点引用走**同一个 Hint**:摘录与完整网址放进第二行。此前这里用裸 Tooltip 画富卡片,
  //: 而工作台右列是原生网页旁边的 DOM 外壳,裸 Tooltip 在那一层没有 Hint 稳定 —— 同一个动作不能有两套
  //: 触发器。截断的胶囊名也交给同一条 Hint 说明(见 tooltip.tsx 的 HintScope)。
  const detail = source.excerpt ? `${source.excerpt}\n${source.href}` : source.href;
  return <Hint label={source.title} hint={detail}><a href={source.href} target={source.kind === "web" ? "_blank" : undefined} rel="noopener noreferrer" aria-label={source.title}
    className="mx-1 inline-flex max-w-[220px] items-center gap-1 rounded-full bg-secondary/70 px-2 py-0.5 align-baseline text-ui-xs font-normal leading-4 text-muted-foreground no-underline transition-colors duration-160 hover:bg-secondary hover:text-foreground motion-reduce:transition-none"><Icon size={11} className="shrink-0" /><Truncate>{source.label}</Truncate></a></Hint>;
}
