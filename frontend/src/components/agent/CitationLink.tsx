import React from "react";
import { BookOpen, Globe } from "lucide-react";
import { canonicalSourceUrl, type Citation } from "./citations";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

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
  return <Tooltip><TooltipTrigger asChild><a href={source.href} target={source.kind === "web" ? "_blank" : undefined} rel="noopener noreferrer" aria-label={source.title}
    className="mx-1 inline-flex max-w-[220px] items-center gap-1 rounded-full bg-secondary/70 px-2 py-0.5 align-baseline text-ui-xs font-normal leading-4 text-muted-foreground no-underline transition-colors duration-150 hover:bg-secondary hover:text-foreground motion-reduce:transition-none"><Icon size={11} className="shrink-0" /><span className="truncate">{source.label}</span></a></TooltipTrigger><TooltipContent className="max-w-xs p-3"><p className="font-medium">{source.title}</p>{source.excerpt && <p className="mt-1 line-clamp-4 leading-relaxed opacity-80">{source.excerpt}</p>}<p className="mt-2 break-all text-ui-2xs opacity-65">{source.href}</p></TooltipContent></Tooltip>;
}
