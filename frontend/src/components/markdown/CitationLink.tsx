import React from "react";
import { BookOpen, Globe } from "lucide-react";
import { canonicalSourceUrl, type Citation } from "./links";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";

export const CitationContext = React.createContext<Map<string, Citation>>(new Map());
export function CitationLink({ href, children }: React.ComponentProps<"a"> & {node?: unknown}) {
  const sources = React.useContext(CitationContext);
  const normalized = canonicalSourceUrl(href);
  const source = normalized ? sources.get(normalized) : undefined;
  if (!source) {
    const safe = normalized || (href?.startsWith("#/") ? href : undefined);
    return safe ? <a href={safe} target={safe.startsWith("#") ? undefined : "_blank"} rel="noopener noreferrer" className="text-primary underline underline-offset-2 break-words">{children}</a> : <span>{children}</span>;
  }
  const Icon = source.kind === "note" ? BookOpen : Globe;
  // 悬停卡片(标题 + 摘录 + 网址)是富内容,不走 Hint。胶囊里截断的名字在卡片里都看得全(网页的域名在网址里、
  // 笔记的名字就是标题),所以它不另出一条:触发器里被截断的字交给卡片,卡片不收(见 tooltip.tsx 的 HintScope)。
  // 摘录不再截成四行:它在 citations.ts 里已经截到 280 字;卡片里再套一层「截断了悬停看全文」的说明,
  // 一悬上去外面这张卡就被顶掉了。
  return <Tooltip><TooltipTrigger asChild><a href={source.href} target={source.kind === "web" ? "_blank" : undefined} rel="noopener noreferrer" aria-label={source.title}
    className="mx-1 inline-flex max-w-[220px] items-center gap-1 rounded-full bg-secondary/70 px-2 py-0.5 align-baseline text-ui-xs font-normal leading-4 text-muted-foreground no-underline transition-colors duration-160 hover:bg-secondary hover:text-foreground motion-reduce:transition-none"><Icon size={11} className="shrink-0" /><Truncate>{source.label}</Truncate></a></TooltipTrigger><TooltipContent className="max-w-xs p-3"><p className="font-medium">{source.title}</p>{source.excerpt && <p className="mt-1 leading-relaxed opacity-80">{source.excerpt}</p>}<p className="mt-2 break-all text-ui-2xs opacity-65">{source.href}</p></TooltipContent></Tooltip>;
}
