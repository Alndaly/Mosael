import React from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, FileText, Play } from "lucide-react";
import { assetFileUrl, assetPreviewUrl, getAsset } from "@/api/client";
import { assetKeys, noteKeys } from "@/api/queryKeys";
import { gotoRecord } from "@/lib/deepLink";
import { getNoteSourceMessage, type NoteSource } from "@/api/domains/notes";
import { noteHref } from "@/lib/deepLink";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { AgentMarkdown } from "@/components/markdown/Markdown";
import { useImagePreview } from "@/components/app/image-preview";
import { IconButton } from "@/components/ui/icon-button";
import { AudioPlayerBar, VideoPlayer } from "@/components/app/media-playback";
import { useNoteStrings } from "./strings";

export function SourceLink({ source, workspaceId }: { source: NoteSource; workspaceId: string }) {
  const s = useNoteStrings();
  const { openImagePreview } = useImagePreview();
  const [open, setOpen] = React.useState(false);
  const asset = useQuery({ queryKey: assetKeys.detail(source.id), queryFn: () => getAsset(source.id), enabled: open && source.kind === "asset" });
  const detail = useQuery({ queryKey: noteKeys.sourceMessage(workspaceId, source.id),
    queryFn: () => getNoteSourceMessage(workspaceId, source.id), enabled: open && source.kind === "message" });
  if (source.kind === "url") return <a href={source.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary"><ExternalLink size={12} />{source.label || source.url}</a>;
  if (source.kind === "note") return <a href={noteHref(source.id, source.revision)} className="inline-flex items-center gap-1 text-primary"><FileText size={12} />{source.label || s.untitled}</a>;
  if (source.kind === "board") return <button type="button" onClick={() => gotoRecord("/boards", "mosael:open-board", source.id)} className="text-primary">{source.label || s.source}</button>;
  return <><button type="button" className="inline-flex max-w-full items-center gap-1 text-primary" onClick={() => setOpen(true)}><Play size={12} />{source.label || s.source}{source.start != null && <span className="whitespace-nowrap"> · {Math.floor(source.start / 60)}:{String(Math.floor(source.start % 60)).padStart(2, "0")}</span>}</button>
    <Dialog open={open} onOpenChange={setOpen}><DialogContent className="max-w-3xl"><DialogTitle className="pr-8 break-words">{source.label || s.source}</DialogTitle>
      {(asset.isError || detail.isError) ? <p>{s.unavailable}</p> : source.kind === "message" ? <div className="max-h-[65vh] overflow-auto"><AgentMarkdown>{detail.data?.content || s.loading}</AgentMarkdown></div> : asset.data ? asset.data.kind === "image" ? <IconButton unstyled label={s.node.preview} className="block w-fit max-w-full cursor-zoom-in border-0 bg-transparent p-0" onClick={() => openImagePreview({ src: assetPreviewUrl(source.id), title: source.label || asset.data?.name })}><img src={assetPreviewUrl(source.id)} alt={source.label} className="max-h-[65vh] object-contain" /></IconButton> : asset.data.kind === "audio" ? <AudioPlayerBar src={assetFileUrl(source.id)} startAt={source.start ?? undefined} endAt={source.end ?? null} className="my-6 h-10 rounded-lg border border-border bg-panel" /> : <div className="aspect-video max-h-[65vh] w-full overflow-hidden rounded-lg"><VideoPlayer assetSrc={assetFileUrl(source.id)} startAt={source.start ?? undefined} endAt={source.end ?? null} /></div> : <p>{s.loading}</p>}
      {source.quote && <blockquote className="text-sm text-muted-foreground">{source.quote}</blockquote>}
    </DialogContent></Dialog></>;
}
