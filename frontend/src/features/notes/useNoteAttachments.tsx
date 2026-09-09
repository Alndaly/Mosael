import React from "react";
import { BookOpen } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { listNotes, type Note } from "@/api/domains/notes";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import type { ComposerChip } from "@/components/agent/ComposerChips";
import { useNoteStrings } from "./strings";

export function useNoteAttachments(workspaceId: string) {
  const s = useNoteStrings(); const [open, setOpen] = React.useState(false); const [q, setQ] = React.useState("");
  const anchor = React.useRef<HTMLElement | null>(null);
  const trigger = React.useRef<HTMLButtonElement | null>(null);
  const virtualAnchor = React.useRef({ getBoundingClientRect: () => (anchor.current || trigger.current)!.getBoundingClientRect() });
  const [active, setActive] = React.useState(0);
  const [selected, setSelected] = React.useState<Note[]>([]);
  const notes = useQuery({queryKey: ["note-attach", workspaceId, q], queryFn: () => listNotes(workspaceId, q), enabled: open});
  React.useEffect(() => { setSelected([]); setOpen(false); }, [workspaceId]);
  React.useEffect(() => setActive(0), [q]);
  function choose(n: Note) { setSelected(old => [...old.filter(x => x.id !== n.id), n]); setOpen(false); }
  function show(element: HTMLElement | null) { anchor.current = element; setQ(""); setActive(0); setOpen(true); }
  return {
    clear: () => setSelected([]),
    context: selected.length ? `用户明确引用的笔记（请先调用 read_note 读取下列固定版本，按需分页，然后在回答中引用 citation_url）：\n${selected.map(n => JSON.stringify({note_id: n.id, workspace_id: workspaceId, revision: n.revision, title: n.title})).join("\n")}` : "",
    summary: selected.map(n => `@${n.title || s.untitled}`).join(" "),
    hasNotes: selected.length > 0,
    onKeyDown: (event: React.KeyboardEvent<HTMLTextAreaElement>) => { if (event.key === "@" && !event.nativeEvent.isComposing) { event.preventDefault(); show(event.currentTarget); return true; } return false; },
    trigger: <button type="button" className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary" ref={trigger} title={s.addReference} aria-label={s.addReference} onClick={() => show(trigger.current)}><BookOpen size={14} /></button>,
    // 小条自己不画了 —— 和附件拼在同一排里,由 ComposerChips 统一渲染(见那边的注释)。
    // 正文点开就能看:listNotes 返回的就是完整的笔记,不必为了预览再问一次服务端。
    chips: selected.map<ComposerChip>(note => ({
      id: note.id,
      label: note.title || s.untitled,
      icon: <BookOpen size={11} />,
      text: { title: note.title || s.untitled, body: note.markdown },
      onRemove: () => setSelected(current => current.filter(x => x.id !== note.id)),
    })),
    dialog: <Popover open={open} onOpenChange={setOpen}><PopoverAnchor virtualRef={virtualAnchor} /><PopoverContent side="top" align="start" className="w-80 p-2" onCloseAutoFocus={event => { event.preventDefault(); anchor.current?.focus(); }}>
      <p className="px-2 py-1 text-xs text-muted-foreground">{s.addReference}</p>
      <Input placeholder={s.search} value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => {
        if (e.nativeEvent.isComposing) return;
        const rows = notes.data || [];
        if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); setActive(i => rows.length ? (i + (e.key === "ArrowDown" ? 1 : -1) + rows.length) % rows.length : 0); }
        if (e.key === "Enter" && rows[active]) { e.preventDefault(); choose(rows[active]); }
      }} />
      <div className="mt-1 max-h-60 overflow-auto" role="listbox">{notes.data?.map((n, index) => <button type="button" role="option" aria-selected={index === active} key={n.id} className={`block w-full truncate rounded-md px-3 py-2 text-left text-sm hover:bg-secondary ${index === active ? "bg-secondary" : ""}`} onClick={() => choose(n)}>{n.title || s.untitled}</button>)}{!notes.data?.length && <p className="p-3 text-xs text-muted-foreground">{notes.isPending ? s.loading : notes.isError ? s.unavailable : s.noResults}</p>}</div>
    </PopoverContent></Popover>,
  };
}
