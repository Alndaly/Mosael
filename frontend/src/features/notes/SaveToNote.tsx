import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BookPlus } from "lucide-react";
import { toast } from "sonner";
import { appendNote, createNote, listNotes, type Note, type NoteSource } from "@/api/domains/notes";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useNoteStrings } from "./strings";

/** 一种可选的正文形状。给了两份以上,对话框就多一排切换;只给正文的调用方什么都不用改。 */
export type SaveToNoteVariant = { id: string; label: string; markdown: string; sources: NoteSource[] };

export function SaveToNote({workspaceId, content, sources = [], variants, className, label, onSaved}: {
  workspaceId: string; content?: string; sources?: NoteSource[]; variants?: SaveToNoteVariant[];
  className?: string; label?: string; onSaved?: (note: Note) => void;
}) {
  const s = useNoteStrings(); const qc = useQueryClient();
  const [open, setOpen] = React.useState(false); const [title, setTitle] = React.useState(""); const [q, setQ] = React.useState(""); const [busy, setBusy] = React.useState(false);
  const [variantId, setVariantId] = React.useState(variants?.[0]?.id ?? "");
  const notes = useQuery({queryKey: ["note-picker", workspaceId, q], queryFn: () => listNotes(workspaceId, q), enabled: open});
  // 选中的那一份没了(调用方换了可选项)就退回第一份,不要停在一个不存在的 id 上。
  const chosen = variants?.find(v => v.id === variantId) ?? variants?.[0];
  const markdown = chosen ? chosen.markdown : (content ?? "");
  const chosenSources = chosen ? chosen.sources : sources;
  async function save(target?: Note) { setBusy(true); try {
    const n = target ? await appendNote(target, markdown, chosenSources) : await createNote(workspaceId, {title: title.trim() || markdown.replace(/[#*>\n]/g, " ").slice(0, 60), markdown, sources: chosenSources});
    void qc.invalidateQueries({queryKey: ["notes", workspaceId]}); void qc.invalidateQueries({queryKey: ["note-picker", workspaceId]}); void qc.invalidateQueries({queryKey: ["note", workspaceId, n.id]});
    toast.success(s.done); onSaved?.(n); setOpen(false);
  } catch (e) { toast.error(String(e)); } finally { setBusy(false); } }
  return <><button type="button" className={className || "inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-secondary"} title={label || s.saveTo} disabled={!markdown.trim()} onClick={() => setOpen(true)}><BookPlus size={13} />{label || s.saveTo}</button>
    <Dialog open={open} onOpenChange={value => { if (!busy) setOpen(value); }}><DialogContent><DialogTitle>{label || s.saveTo}</DialogTitle>
      {variants && variants.length > 1 && <div className="flex gap-1" role="radiogroup" aria-label={s.shape}>{variants.map(variant =>
        <button key={variant.id} type="button" role="radio" aria-checked={variant.id === chosen?.id} disabled={busy}
          className={`rounded-md px-3 py-1.5 text-xs transition-colors ${variant.id === chosen?.id ? "bg-secondary font-medium" : "text-muted-foreground hover:bg-secondary/60"}`}
          onClick={() => setVariantId(variant.id)}>{variant.label}</button>)}</div>}
      {variants && <p className="text-xs text-muted-foreground">{s.willSave(markdown.length, chosenSources.length)}</p>}
      <div className="flex gap-2"><Input aria-label={s.title} value={title} onChange={e => setTitle(e.target.value)} placeholder={s.untitled} maxLength={240} /><Button disabled={busy} onClick={() => void save()}>{s.new}</Button></div><p className="text-xs text-muted-foreground">{s.append}</p><Input value={q} onChange={e => setQ(e.target.value)} placeholder={s.search} /><div className="max-h-64 overflow-auto">{notes.data?.filter(n => !n.trashed).map(n => <button disabled={busy} key={n.id} className="block w-full truncate rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-secondary" onClick={() => void save(n)}>{n.title || s.untitled}</button>)}</div></DialogContent></Dialog>
  </>;
}
