import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BookPlus } from "lucide-react";
import { toast } from "sonner";
import { appendNote, createNote, listNotes, type Note, type NoteSource } from "@/api/domains/notes";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useNoteStrings } from "./strings";

export function SaveToNote({workspaceId, content, sources = [], className, onSaved}: {
  workspaceId: string; content: string; sources?: NoteSource[]; className?: string; onSaved?: (note: Note) => void;
}) {
  const s = useNoteStrings(); const qc = useQueryClient();
  const [open, setOpen] = React.useState(false); const [title, setTitle] = React.useState(""); const [q, setQ] = React.useState(""); const [busy, setBusy] = React.useState(false);
  const notes = useQuery({queryKey: ["note-picker", workspaceId, q], queryFn: () => listNotes(workspaceId, q), enabled: open});
  async function save(target?: Note) { setBusy(true); try {
    const n = target ? await appendNote(target, content, sources) : await createNote(workspaceId, {title: title.trim() || content.replace(/[#*>\n]/g, " ").slice(0, 60), markdown: content, sources});
    void qc.invalidateQueries({queryKey: ["notes", workspaceId]}); void qc.invalidateQueries({queryKey: ["note-picker", workspaceId]}); void qc.invalidateQueries({queryKey: ["note", workspaceId, n.id]});
    toast.success(s.done); onSaved?.(n); setOpen(false);
  } catch (e) { toast.error(String(e)); } finally { setBusy(false); } }
  return <><button type="button" className={className || "inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-secondary"} title={s.saveTo} disabled={!content.trim()} onClick={() => setOpen(true)}><BookPlus size={13} />{s.saveTo}</button>
    <Dialog open={open} onOpenChange={value => { if (!busy) setOpen(value); }}><DialogContent><DialogTitle>{s.saveTo}</DialogTitle><div className="flex gap-2"><Input aria-label={s.title} value={title} onChange={e => setTitle(e.target.value)} placeholder={s.untitled} maxLength={240} /><Button disabled={busy} onClick={() => void save()}>{s.new}</Button></div><p className="text-xs text-muted-foreground">{s.append}</p><Input value={q} onChange={e => setQ(e.target.value)} placeholder={s.search} /><div className="max-h-64 overflow-auto">{notes.data?.filter(n => !n.trashed).map(n => <button disabled={busy} key={n.id} className="block w-full truncate rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-secondary" onClick={() => void save(n)}>{n.title || s.untitled}</button>)}</div></DialogContent></Dialog>
  </>;
}
