import React from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, SearchX, Plus, Star, Download, Upload, PanelLeftClose, PanelLeftOpen, History, Info, Trash2, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { api, type Workspace } from "@/api/client";
import { ApiError } from "@/api/transport";
import { createNote, getNote, listNotes, noteHref, openNote, saveNote, type Note, type NoteContent } from "@/api/domains/notes";
import { ConfirmDialog } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { NoteEditor, NoteReader } from "./NoteEditor";
import { SourceLink } from "./NoteSources";
import { useNoteStrings } from "./strings";
import "./notes.css";

function locationNote() { return new URLSearchParams(window.location.hash.split("?")[1] || "").get("note"); }
export function exportMarkdown(note: Pick<Note, "title" | "markdown" | "sources">) {
  const sources = note.sources.map(source => `- ${source.label || source.kind}${source.kind === "url" ? `: ${source.url}` : source.kind === "note" ? `: ${noteHref(source.id, source.revision)}` : ` [${source.kind}:${source.id}${source.start != null ? ` @ ${source.start}–${source.end ?? ""}s` : ""}]`}`).join("\n");
  const blob = new Blob([`# ${note.title}\n\n${note.markdown}${sources ? `\n\n---\n\n${sources}\n` : ""}`], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = `${(note.title || "note").replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").slice(0, 100)}.md`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function NotesView({ workspace }: { workspace: Workspace }) {
  const s = useNoteStrings(); const qc = useQueryClient();
  const [id, setId] = React.useState(locationNote);
  const [q, setQ] = React.useState(""); const search = React.useDeferredValue(q);
  const [filter, setFilter] = React.useState("all"); const [topic, setTopic] = React.useState("");
  const [focus, setFocus] = React.useState(() => !!locationNote() && window.matchMedia("(max-width: 740px)").matches); const input = React.useRef<HTMLInputElement>(null);
  React.useEffect(() => { const read = () => setId(locationNote()); window.addEventListener("hashchange", read); return () => window.removeEventListener("hashchange", read); }, []);
  const notes = useInfiniteQuery({ queryKey: ["notes", workspace.id, search, filter === "trash"], initialPageParam: 0,
    queryFn: ({ pageParam }) => listNotes(workspace.id, search, filter === "trash", pageParam), getNextPageParam: (last, pages) => last.length === 200 ? pages.length * 200 : undefined });
  const rows = notes.data?.pages.flat() || [];
  const topics = [...new Set(rows.flatMap(n => n.topics))];
  const shown = rows.filter(n => (filter !== "favorite" || n.favorite) && (!topic || n.topics.includes(topic)));
  const selected = useQuery({ queryKey: ["note", workspace.id, id], queryFn: () => getNote(workspace.id, id!), enabled: !!id });
  async function add(markdown = "", title = "") { try { const n = await createNote(workspace.id, { title, markdown }); void qc.invalidateQueries({ queryKey: ["notes", workspace.id] }); openNote(n.id); if (window.matchMedia("(max-width: 740px)").matches) setFocus(true); } catch (e) { toast.error(String(e)); } }
  return <div className={`notes-layout ${!focus ? "notes-show-list" : ""}`}>
    {!focus && <aside className="notes-index"><header><h1>{s.title}</h1><button className="note-icon" aria-label={s.new} title={s.new} onClick={() => void add()}><Plus size={17} /></button></header>
      <Input aria-label={s.search} placeholder={s.search} value={q} onChange={e => setQ(e.target.value)} />
      <nav className="notes-filter">{[["all", s.all], ["favorite", s.favorite], ["trash", s.trash]].map(([key, label]) => <button key={key} aria-pressed={filter === key} onClick={() => { setFilter(key); setTopic(""); }}>{label}</button>)}</nav>
      {!!topics.length && <SearchableSelect value={topic} onValueChange={setTopic} options={[{value: "", label: s.topics}, ...topics.map(t => ({value:t,label:t}))]} placeholder={s.topics} />}
      <div className={`notes-list ${!shown.length ? "notes-list-empty" : ""}`}>{notes.isError ? <p>{String(notes.error)}</p> : notes.isPending ? <p className="p-3 text-xs text-muted-foreground">{s.loading}</p> : shown.length ? shown.map(n => <button key={n.id} className="note-list-row" aria-current={id === n.id} onClick={() => { openNote(n.id); if (window.matchMedia("(max-width: 740px)").matches) setFocus(true); }}><strong>{n.favorite && "☆ "}{n.title || s.untitled}</strong><p>{n.markdown.replace(/[#*>`]/g, "").slice(0, 160)}</p><time>{new Date(n.updated_at).toLocaleDateString()}{n.topics.length ? ` · ${n.topics.join(", ")}` : ""}</time></button>) : <div className="note-empty-state"><span className="note-empty-icon">{search || topic ? <SearchX size={24} strokeWidth={1.5} /> : filter === "trash" ? <Trash2 size={24} strokeWidth={1.5} /> : filter === "favorite" ? <Star size={24} strokeWidth={1.5} /> : <BookOpen size={24} strokeWidth={1.5} />}</span><strong>{search || topic ? s.noResults : filter === "trash" ? s.trashEmpty : filter === "favorite" ? s.favoriteEmpty : s.listEmpty}</strong><p>{search || topic ? s.searchHint : filter === "trash" ? s.trashHint : filter === "favorite" ? s.favoriteHint : s.listEmptyHint}</p>{search || topic ? <Button variant="ghost" size="sm" onClick={() => { setQ(""); setTopic(""); }}>{s.clearSearch}</Button> : filter === "all" ? <Button variant="ghost" size="sm" onClick={() => void add()}><Plus size={14} />{s.new}</Button> : null}</div>}{notes.hasNextPage && <Button variant="ghost" onClick={() => void notes.fetchNextPage()}>{s.more}</Button>}</div>
      <Button variant="ghost" size="sm" onClick={() => input.current?.click()}><Upload size={14} />{s.import}</Button><input hidden ref={input} type="file" accept=".md,.markdown,.txt" onChange={e => { const file = e.target.files?.[0]; if (file) { if (file.size > 500000) toast.error("Maximum 500 KB"); else void file.text().then(text => add(text, file.name.replace(/\.[^.]+$/, ""))); } e.target.value = ""; }} />
    </aside>}
    {selected.data ? <NoteDocument key={`${workspace.id}:${selected.data.id}`} note={selected.data} focus={focus} onFocus={() => setFocus(!focus)} /> : <main className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 p-8 text-center"><BookOpen size={28} className="text-muted-foreground" /><h2 className="text-lg font-medium">{selected.isError ? s.unavailable : id ? s.loading : s.empty}</h2><p className="max-w-sm text-sm leading-relaxed text-muted-foreground">{!id && s.emptyHint}</p>{id && selected.isError && <Button onClick={() => void add()}><Plus size={15} />{s.new}</Button>}</main>}
  </div>;
}

function NoteDocument({ note, focus, onFocus }: { note: Note; focus: boolean; onFocus: () => void }) {
  const s = useNoteStrings(); const qc = useQueryClient();
  const storageKey = `mosael.note.draft.${note.workspace_id}.${note.id}`;
  const [draft, setDraft] = React.useState<Note>(() => { try { const cached = JSON.parse(localStorage.getItem(storageKey) || "null") as Note | null; return cached?.id === note.id && cached.workspace_id === note.workspace_id ? cached : note; } catch { return note; } });
  const latest = React.useRef(draft); latest.current = draft;
  const saved = React.useRef(JSON.stringify(note)); const busy = React.useRef(false); const mounted = React.useRef(true);
  const [status, setStatus] = React.useState(JSON.stringify(draft) === JSON.stringify(note) ? "saved" : "draft"); const [error, setError] = React.useState("");
  const [mode, setMode] = React.useState("edit"); const [properties, setProperties] = React.useState(false);
  const [history, setHistory] = React.useState(false);
  const [confirmDelete, setConfirmDelete] = React.useState(false); const [deleting, setDeleting] = React.useState(false);
  const historyPreview = React.useRef<HTMLDivElement>(null);
  const historyRequest = React.useRef(0);
  const [pendingVersion, setPendingVersion] = React.useState<number | null>(null);
  const [historic, setHistoric] = React.useState<(NoteContent & {revision: number}) | null>(null);
  const revisions = useQuery({ queryKey: ["note-history", note.id, draft.revision], queryFn: () => api<{revision: number; title: string; created_at: string}[]>(`/api/notes/${note.id}/revisions?workspace_id=${note.workspace_id}`), enabled: history });
  const loadVersion = React.useCallback(async (revision: number) => {
    const request = ++historyRequest.current; setPendingVersion(revision);
    try {
      const value = await api<NoteContent & {revision: number}>(`/api/notes/${note.id}/revisions/${revision}?workspace_id=${note.workspace_id}`);
      if (request === historyRequest.current) { setHistoric(value); if (historyPreview.current) historyPreview.current.scrollTop = 0; }
    } catch (e) { if (request === historyRequest.current) toast.error(String(e)); }
    finally { if (request === historyRequest.current) setPendingVersion(null); }
  }, [note.id, note.workspace_id]);
  React.useEffect(() => { if (historyPreview.current) historyPreview.current.scrollTop = 0; }, [historic?.revision]);
  function change(patch: Partial<NoteContent>) { const next = {...latest.current, ...patch}; latest.current = next; try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* Server autosave remains available when device storage is full. */ } setDraft(next); setStatus("draft"); }
  const persist = React.useCallback(async () => {
    if (busy.current || JSON.stringify(latest.current) === saved.current) return;
    busy.current = true; if (mounted.current) setStatus("saving"); const sent = latest.current;
    try { const result = await saveNote(sent); saved.current = JSON.stringify(result);
      const current = latest.current; const next = current === sent ? result : {...current, revision: result.revision, updated_at: result.updated_at}; latest.current = next;
      if (current === sent) localStorage.removeItem(storageKey); else { try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* Keep the live draft. */ } }
      if (mounted.current) { setDraft(next); setStatus(current === sent ? "saved" : "draft"); setError(""); }
      qc.setQueryData(["note", note.workspace_id, note.id], result); void qc.invalidateQueries({queryKey: ["notes", note.workspace_id]});
    } catch (e) { if (mounted.current) { setError(e instanceof ApiError && e.status === 409 ? s.conflict : String(e)); setStatus("error"); } }
    finally { busy.current = false; }
  }, [note.id, note.workspace_id, qc, s.conflict, storageKey]);
  React.useEffect(() => { if (status === "error") return; const timer = setTimeout(() => void persist(), 700); return () => clearTimeout(timer); }, [draft, status, persist]);
  React.useEffect(() => { mounted.current = true; const unload = (e: BeforeUnloadEvent) => { if (JSON.stringify(latest.current) !== saved.current) { e.preventDefault(); e.returnValue = ""; } }; window.addEventListener("beforeunload", unload); return () => { mounted.current = false; window.removeEventListener("beforeunload", unload); void persist(); }; }, [persist]);
  React.useEffect(() => {
    const readRevision = () => {
      const params = new URLSearchParams(window.location.hash.split("?")[1]);
      if (params.get("note") !== note.id) return;
      const revision = Number(params.get("revision"));
      if (revision > 0) { setHistory(true); void loadVersion(revision); }
    };
    readRevision(); window.addEventListener("hashchange", readRevision);
    return () => window.removeEventListener("hashchange", readRevision);
  }, [note.id, loadVersion]);
  async function restore() { if (!historic || busy.current) return; await persist(); if (JSON.stringify(latest.current) !== saved.current) return; try { const next = await api<Note>(`/api/notes/${note.id}/restore`, {method: "POST", body: JSON.stringify({workspace_id: note.workspace_id, base_revision: latest.current.revision, revision: historic.revision})}); saved.current = JSON.stringify(next); latest.current = next; setDraft(next); setHistoric(null); setHistory(false); setStatus("saved"); localStorage.removeItem(storageKey); qc.setQueryData(["note", note.workspace_id, note.id], next); void qc.invalidateQueries({queryKey: ["notes", note.workspace_id]}); } catch (e) { toast.error(String(e)); } }
  async function deleteForever() {
    if (deleting || busy.current) return;
    await persist();
    if (JSON.stringify(latest.current) !== saved.current) return;
    setDeleting(true);
    try {
      await api(`/api/notes/${note.id}?workspace_id=${encodeURIComponent(note.workspace_id)}&base_revision=${latest.current.revision}`, {method:"DELETE"});
      localStorage.removeItem(storageKey);
      window.location.hash = "#/notes";
      qc.removeQueries({queryKey:["note", note.workspace_id, note.id]});
      qc.removeQueries({queryKey:["note-history", note.id]});
      void qc.invalidateQueries({queryKey:["notes", note.workspace_id]});
    } catch (e) { toast.error(String(e)); setDeleting(false); }
  }
  return <><main className="note-document"><header className="note-document-header"><button className="note-icon" title={focus ? s.exitFocus : s.focus} onClick={onFocus}>{focus ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}</button><span className="note-status" role="status">{status === "saving" ? s.saving : status === "error" ? s.error : status === "draft" ? s.draft : s.saved}</span>
      {(["edit", "read", "raw"] as const).map((m, i) => <button key={m} className={`rounded-md px-2 py-1 ${mode === m ? "bg-secondary text-foreground" : ""}`} onClick={() => setMode(m)}>{[s.write, s.preview, s.raw][i]}</button>)}
      <button className="note-icon" aria-label={s.favorite} aria-pressed={draft.favorite} onClick={() => change({favorite: !draft.favorite})}><Star size={15} fill={draft.favorite ? "currentColor" : "none"} /></button>
      <button className="note-icon" title={s.export} onClick={() => exportMarkdown(draft)}><Download size={15} /></button><button className="note-icon" title={s.history} onClick={() => setHistory(true)}><History size={15} /></button><button className="note-icon" title={s.source} onClick={() => setProperties(!properties)}><Info size={15} /></button><button className="note-icon" title={draft.trashed ? s.restoreTrash : s.moveTrash} onClick={() => change({trashed: !draft.trashed})}>{draft.trashed ? <RotateCcw size={15} /> : <Trash2 size={15} />}</button>
    </header>{draft.trashed && <div className="mx-5 mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-secondary/50 px-3 py-2 text-ui-xs text-muted-foreground"><span>{s.inTrash}</span><Button variant="ghost" size="sm" className="text-destructive" disabled={deleting} onClick={() => setConfirmDelete(true)}><Trash2 size={14} />{s.deleteForever}</Button></div>}{error && <div className="px-6 text-sm text-destructive" role="alert">{error}<Button variant="ghost" onClick={() => void persist()}>{s.retry}</Button><Button variant="ghost" onClick={() => { exportMarkdown(draft); void getNote(note.workspace_id, note.id).then(n => { saved.current = JSON.stringify(n); latest.current = n; setDraft(n); setStatus("saved"); setError(""); localStorage.removeItem(storageKey); }); }}>{s.reload}</Button></div>}
    <div className="note-body"><article className="note-paper">
      {mode === "raw" ? <><textarea aria-label={s.title} className="note-title" rows={1} placeholder={s.untitled} value={draft.title} maxLength={240} disabled={draft.trashed} onChange={e => change({title: e.target.value})} /><textarea className="note-raw" rows={1} spellCheck={false} maxLength={500000} aria-label={s.content} value={draft.markdown} disabled={draft.trashed} onChange={e => change({markdown: e.target.value})} /></> : <NoteEditor key={mode} markdown={draft.markdown} onChange={markdown => change({markdown})} editable={mode === "edit" && !draft.trashed} workspaceId={note.workspace_id} noteId={note.id}
        title={<textarea aria-label={s.title} className="note-title" rows={1} placeholder={s.untitled} value={draft.title} maxLength={240} disabled={draft.trashed || mode === "read"} onChange={e => change({title: e.target.value})} />}
        onReference={n => { if (!latest.current.sources.some(source => source.kind === "note" && source.id === n.id && source.revision === n.revision)) change({sources: [...latest.current.sources, {kind: "note", id: n.id, label: n.title, quote: "", revision: n.revision}]}); }} />}
    </article></div></main>
    {properties && <aside className="note-properties"><strong>{s.source}</strong><label>{s.topics}</label><Input placeholder={s.topicHint} value={draft.topics.join(", ")} onChange={e => change({topics: e.target.value.split(/[,，]/)})} /><label>{s.tags}</label><Input placeholder={s.tagHint} value={draft.tags.join(", ")} onChange={e => change({tags: e.target.value.split(/[,，]/)})} /><label>{s.source}</label>{draft.sources.length ? draft.sources.map((source, i) => <div className="note-source" key={i}><SourceLink source={source} workspaceId={note.workspace_id} />{source.quote && <blockquote>{source.quote}</blockquote>}</div>) : <p className="leading-relaxed text-muted-foreground">{s.sourcesEmpty}</p>}</aside>}
    <ConfirmDialog open={confirmDelete} title={`${s.deleteForever} · ${draft.title || s.untitled}`} body={s.deleteWarning} onCancel={() => { if (!deleting) setConfirmDelete(false); }} onConfirm={() => void deleteForever()} />
    <Dialog open={history} onOpenChange={setHistory}><DialogContent className="flex h-[min(80dvh,800px)] max-w-5xl flex-col gap-4 overflow-hidden">
      <DialogTitle className="shrink-0">{s.history}</DialogTitle><p className="shrink-0 text-sm text-muted-foreground">{s.historyHint}</p>
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(100px,160px)_minmax(0,1fr)] gap-4 sm:gap-6">
        <div className="note-history-list min-h-0 overflow-y-auto overscroll-contain pr-1" aria-label={s.history}>
          {revisions.data?.map(r => <button key={r.revision} className="note-list-row" aria-current={(pendingVersion ?? historic?.revision) === r.revision} onClick={() => void loadVersion(r.revision)}>{s.version} {r.revision}<time>{new Date(r.created_at).toLocaleString()}</time></button>)}
        </div>
        <div ref={historyPreview} className="note-history-preview min-h-0 min-w-0 overflow-y-auto overscroll-contain pr-1" aria-label={s.preview}>
          {pendingVersion ? <p className="p-4 text-sm text-muted-foreground">{s.loading}</p> : historic ? <><h3 className="mb-5 break-words text-lg font-semibold">{historic.title}</h3><NoteReader markdown={historic.markdown} /></> : <p className="p-4 text-sm text-muted-foreground">{s.chooseVersion}</p>}
        </div>
      </div>
      <div className="flex shrink-0 justify-end"><Button disabled={!historic || !!pendingVersion} onClick={() => void restore()}>{s.restore}</Button></div>
    </DialogContent></Dialog>
  </>;
}
