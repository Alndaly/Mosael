import React from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, FileText, Play } from "lucide-react";
import { api, assetFileUrl, assetPreviewUrl, type Asset } from "@/api/client";
import { gotoRecord } from "@/lib/deepLink";
import { type NoteSource, noteHref } from "@/api/domains/notes";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { AgentMarkdown } from "@/components/agent/Markdown";
import { useNoteStrings } from "./strings";

export function SourceLink({ source, workspaceId }: { source: NoteSource; workspaceId: string }) {
  const s = useNoteStrings();
  const [open, setOpen] = React.useState(false);
  const asset = useQuery({ queryKey: ["note-source", "asset", source.id], queryFn: () => api<Asset>(`/api/assets/${source.id}`), enabled: open && source.kind === "asset" });
  const detail = useQuery({ queryKey: ["note-source", workspaceId, source.kind, source.id],
    queryFn: () => api<{ content: string }>(`/api/notes/sources/message/${source.id}?workspace_id=${encodeURIComponent(workspaceId)}`), enabled: open && source.kind === "message" });
  if (source.kind === "url") return <a href={source.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary"><ExternalLink size={12} />{source.label || source.url}</a>;
  if (source.kind === "note") return <a href={noteHref(source.id, source.revision)} className="inline-flex items-center gap-1 text-primary"><FileText size={12} />{source.label || s.untitled}</a>;
  if (source.kind === "board") return <button type="button" onClick={() => gotoRecord("/boards", "mosael:open-board", source.id)} className="text-primary">{source.label || s.source}</button>;
  return <><button type="button" className="inline-flex max-w-full items-center gap-1 text-primary" onClick={() => setOpen(true)}><Play size={12} />{source.label || s.source}{source.start != null && <span className="whitespace-nowrap"> · {Math.floor(source.start / 60)}:{String(Math.floor(source.start % 60)).padStart(2, "0")}</span>}</button>
    <Dialog open={open} onOpenChange={setOpen}><DialogContent className="max-w-3xl"><DialogTitle className="pr-8 break-words">{source.label || s.source}</DialogTitle>
      {(asset.isError || detail.isError) ? <p>{s.unavailable}</p> : source.kind === "message" ? <div className="max-h-[65vh] overflow-auto"><AgentMarkdown>{detail.data?.content || s.loading}</AgentMarkdown></div> : asset.data ? asset.data.kind === "image" ? <img src={assetPreviewUrl(source.id)} alt={source.label} className="max-h-[65vh] object-contain" /> : asset.data.kind === "audio" ? <audio controls src={assetFileUrl(source.id)} className="my-6 w-full" onLoadedMetadata={e => { e.currentTarget.currentTime = source.start || 0; }} onTimeUpdate={e => { if (source.end != null && e.currentTarget.currentTime >= source.end) e.currentTarget.pause(); }} /> : <video controls autoPlay={false} src={assetFileUrl(source.id)} className="max-h-[65vh] w-full" onLoadedMetadata={e => { e.currentTarget.currentTime = source.start || 0; }} onTimeUpdate={e => { if (source.end != null && e.currentTarget.currentTime >= source.end) e.currentTarget.pause(); }} /> : <p>{s.loading}</p>}
      {source.quote && <blockquote className="text-sm text-muted-foreground">{source.quote}</blockquote>}
    </DialogContent></Dialog></>;
}
