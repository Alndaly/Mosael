import React from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, BookOpen, CheckSquare, SearchX, MoreHorizontal, Check, Loader2, PenLine, X, Plus, Star, Download, Upload, PanelLeftClose, PanelLeftOpen, History, Info, Trash2, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { api, type Workspace } from "@/api/client";
import { ApiError } from "@/api/transport";
import { PageLoadError } from "@/components/layout/EmptyState";
import { createNote, getNote, listNotes, noteHref, openNote, saveNote, type Note, type NoteContent } from "@/api/domains/notes";
import { errorText } from "@/api/errorMessage";
import { ConfirmDialog } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { MENU_ITEM, MENU_SEPARATOR } from "@/components/ui/floating";
import { useFileDrop } from "@/lib/useFileDrop";
import { useResizableSidebar } from "@/lib/useResizableSidebar";
import { cn } from "@/lib/utils";
import { NoteEditor, NoteReader } from "./NoteEditor";
import { SourceLink } from "./NoteSources";
import { useNoteStrings } from "./strings";
import { NoteList, type NoteListAction } from "./NoteList";
import { mergeAppendedNote } from "./appendMerge";
import "./notes.css";
type NoteController = { id:string; read:()=>Note; update:(patch:Partial<NoteContent>)=>Promise<Note> };


function locationNote() { return new URLSearchParams(window.location.hash.split("?")[1] || "").get("note"); }
//: 每个工作区最后打开的那篇。打开哪篇只写在地址里(`#/notes?note=…`),切到别的页再回来地址就成了
//: `#/notes`,于是又是一片空 —— 刚才正在看的东西没了。
const lastNoteKey = (workspaceId: string) => `mosael.notes.last.${workspaceId}`;
function rememberedNote(workspaceId: string) { try { return window.localStorage.getItem(lastNoteKey(workspaceId)); } catch { return null; } }
function rememberNote(workspaceId: string, id: string | null) {
  try { if (id) window.localStorage.setItem(lastNoteKey(workspaceId), id); else window.localStorage.removeItem(lastNoteKey(workspaceId)); } catch { /* 记不住只是少一个便利 */ }
}
const MARKDOWN_IMPORT_LIMIT = 500_000;
const isMarkdownFile = (file: File) => /\.(md|markdown|txt)$/i.test(file.name);
export function exportMarkdown(note: Pick<Note, "title" | "markdown" | "sources">) {
  const sources = note.sources.map(source => `- ${source.label || source.kind}${source.kind === "url" ? `: ${source.url}` : source.kind === "note" ? `: ${noteHref(source.id, source.revision)}` : ` [${source.kind}:${source.id}${source.start != null ? ` @ ${source.start}–${source.end ?? ""}s` : ""}]`}`).join("\n");
  const blob = new Blob([`# ${note.title}\n\n${note.markdown}${sources ? `\n\n---\n\n${sources}\n` : ""}`], { type: "text/markdown;charset=utf-8" });
  // 控制字符是故意的:这是文件名净化,\x00-\x1f 在各家文件系统上都非法,和 <>:"/\\|?* 一起替掉。
  // eslint-disable-next-line no-control-regex
  const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = `${(note.title || "note").replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").slice(0, 100)}.md`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function NotesView({ workspace }: { workspace: Workspace }) {
  const s = useNoteStrings(); const qc = useQueryClient();
  const [id, setId] = React.useState(() => locationNote() ?? rememberedNote(workspace.id));
  // 从记住的那篇打开时把地址补上,和点开一篇的状态一样(刷新、返回都认它)。
  React.useEffect(() => { if (id && !locationNote()) window.history.replaceState(null, "", noteHref(id)); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  React.useEffect(() => { if (id) rememberNote(workspace.id, id); }, [workspace.id, id]);
  const sidebar = useResizableSidebar("notes", { min: 220, max: 480, fallback: 260 });
  const [selecting,setSelecting] = React.useState(false);
  const controller = React.useRef<NoteController | null>(null);

  const [q, setQ] = React.useState(""); const search = React.useDeferredValue(q);
  const [filter, setFilter] = React.useState("all"); const [topic, setTopic] = React.useState("");
  const [focus, setFocus] = React.useState(() => !!locationNote() && window.matchMedia("(max-width: 740px)").matches); const input = React.useRef<HTMLInputElement>(null);
  React.useEffect(() => { const read = () => setId(locationNote()); window.addEventListener("hashchange", read); return () => window.removeEventListener("hashchange", read); }, []);
  const notes = useInfiniteQuery({ queryKey: ["notes", workspace.id, search, filter === "trash"], initialPageParam: 0,
    queryFn: ({ pageParam }) => listNotes(workspace.id, search, filter === "trash", pageParam), getNextPageParam: (last, pages) => last.length === 200 ? pages.length * 200 : undefined });
  const rows = notes.data?.pages.flat() || [];
  const topics = [...new Set(rows.flatMap(n => n.topics))];
  const shown = rows.filter(n => (filter !== "favorite" || n.favorite) && (!topic || n.topics.includes(topic)));
  // 打开一篇就重新取一次(staleTime 0):缓存里的那份可能是移进回收站、收藏之前的,打开后看到的
  // 就是错的状态 —— 回收站里的笔记没有提示条、还能编辑。
  const selected = useQuery({ queryKey: ["note", workspace.id, id], queryFn: () => getNote(workspace.id, id!), enabled: !!id, staleTime: 0 });
  // 记住的那篇已经删了:不再自动打开它。
  React.useEffect(() => { if (selected.isError && id === rememberedNote(workspace.id)) rememberNote(workspace.id, null); }, [selected.isError, id, workspace.id]);
  async function listAction(action:NoteListAction, targets:Note[], value?:string) {
    const done:string[]=[];let failed=0;
    for(const target of targets) {
      try {
        const active=controller.current?.id===target.id?controller.current:null;
        const current=active?active.read():await getNote(workspace.id,target.id);
        if(action==="export") exportMarkdown(current);
        else if(action==="duplicate") await createNote(workspace.id,{markdown:current.markdown,project_id:current.project_id,tags:current.tags,topics:current.topics,sources:current.sources,title:`${current.title||s.untitled} · ${s.copySuffix}`,trashed:false});
        else if(action==="delete") {
          if(!current.trashed)throw new Error("Move to trash first");
          await api(`/api/notes/${current.id}?workspace_id=${encodeURIComponent(workspace.id)}&base_revision=${current.revision}`,{method:"DELETE"});
          localStorage.removeItem(`mosael.note.draft.${workspace.id}.${current.id}`);
          qc.removeQueries({queryKey:["note",workspace.id,current.id]});
          qc.removeQueries({queryKey:["note-history",current.id]});
        } else {
          const patch:Partial<NoteContent>=action==="rename"?{title:value||""}:action==="trash"||action==="restore"?{trashed:action==="trash"}:{favorite:action==="favorite"};
          const result=active?await active.update(patch):await saveNote({...current,...patch});
          qc.setQueryData(["note",workspace.id,current.id],result);
        }
        done.push(target.id);
      }catch(e){failed++;toast.error(errorText(e));}
    }
    await qc.invalidateQueries({queryKey:["notes",workspace.id]});
    if(["trash","restore","delete"].includes(action)&&id&&done.includes(id)){rememberNote(workspace.id,null);window.location.hash="#/notes";}
    if(failed)toast.error(s.partialFailure(failed));
    return done;
  }
  async function add(markdown = "", title = "") { try { setFilter("all"); setQ(""); setTopic(""); const n = await createNote(workspace.id, { title, markdown }); void qc.invalidateQueries({ queryKey: ["notes", workspace.id] }); openNote(n.id); if (window.matchMedia("(max-width: 740px)").matches) setFocus(true); } catch (e) { toast.error(errorText(e)); } }
  //: 导入一批 Markdown:按钮多选和拖进来是同一条路。逐篇建,一篇失败不拦后面的;建完打开最后一篇。
  async function importFiles(files: File[]) {
    const accepted = files.filter(isMarkdownFile);
    if (!accepted.length) { toast.error(s.importUnsupported); return; }
    setFilter("all"); setQ(""); setTopic("");
    let last: Note | null = null; const failed: string[] = [];
    for (const file of accepted) {
      if (file.size > MARKDOWN_IMPORT_LIMIT) { failed.push(file.name); continue; }
      try { last = await createNote(workspace.id, { title: file.name.replace(/\.[^.]+$/, ""), markdown: await file.text() }); }
      catch { failed.push(file.name); }
    }
    void qc.invalidateQueries({ queryKey: ["notes", workspace.id] });
    if (last) openNote(last.id);
    const imported = accepted.length - failed.length;
    if (failed.length) toast.error(s.importPartial(imported, failed));
    else if (imported > 1) toast.success(s.imported(imported));
  }
  // 只拖图片/音视频时不接:那是往正文里插图(编辑器自己处理),不是导入笔记。
  const drop = useFileDrop(files => void importFiles(files), isMarkdownFile, types => types.some(type => !/^(image|video|audio)\//.test(type)));
  return <div className={`notes-layout ${!focus ? "notes-show-list" : ""}`} {...drop.handlers}>
    {drop.active && <div className="notes-drop" aria-hidden="true"><span><Upload size={20} />{s.dropHint}</span></div>}
    {!focus && <aside className="notes-index" style={{ "--notes-index-width": `${sidebar.width}px` } as React.CSSProperties}><header><h1>{s.title}</h1><div className="flex shrink-0 items-center gap-1"><button className="note-icon" aria-label={s.import} title={s.import} onClick={() => input.current?.click()}><Upload size={16} /></button><button className="note-icon" title={s.selectNotes} aria-label={s.selectNotes} aria-pressed={selecting} onClick={()=>setSelecting(!selecting)}><CheckSquare size={16}/></button><button className="note-icon" aria-label={s.new} title={s.new} onClick={() => void add()}><Plus size={16} /></button></div></header>
      <Input aria-label={s.search} placeholder={s.search} value={q} onChange={e => setQ(e.target.value)} />
      <nav className="notes-filter">{[["all", s.all], ["favorite", s.favorite], ["trash", s.trash]].map(([key, label]) => <button key={key} aria-pressed={filter === key} onClick={() => { setFilter(key); setTopic(""); window.location.hash = "#/notes"; }}>{label}</button>)}</nav>
      {!!topics.length && <SearchableSelect value={topic} onValueChange={setTopic} options={[{value: "", label: s.topics}, ...topics.map(t => ({value:t,label:t}))]} placeholder={s.topics} />}
      <NoteList key={`${workspace.id}:${search}:${filter}:${topic}`} notes={shown} currentId={id} selecting={selecting} onSelecting={setSelecting}
        onOpen={noteId=>{openNote(noteId);if(window.matchMedia("(max-width: 740px)").matches)setFocus(true);}}
        onAction={listAction} empty={notes.isError?<PageLoadError size="compact" icon={<BookOpen size={15} />} error={notes.error} onRetry={() => void notes.refetch()} />:notes.isPending?<p className="p-3 text-xs text-muted-foreground">{s.loading}</p>:<div className="note-empty-state"><span className="note-empty-icon">{search || topic ? <SearchX size={24} strokeWidth={1.5} /> : filter === "trash" ? <Trash2 size={24} strokeWidth={1.5} /> : filter === "favorite" ? <Star size={24} strokeWidth={1.5} /> : <BookOpen size={24} strokeWidth={1.5} />}</span><strong>{search || topic ? s.noResults : filter === "trash" ? s.trashEmpty : filter === "favorite" ? s.favoriteEmpty : s.listEmpty}</strong><p>{search || topic ? s.searchHint : filter === "trash" ? s.trashHint : filter === "favorite" ? s.favoriteHint : s.listEmptyHint}</p>{search || topic ? <Button variant="ghost" size="sm" onClick={() => { setQ(""); setTopic(""); }}>{s.clearSearch}</Button> : filter === "all" ? <Button variant="ghost" size="sm" onClick={() => void add()}><Plus size={14} />{s.new}</Button> : null}</div>} more={notes.hasNextPage&&<Button variant="ghost" onClick={()=>void notes.fetchNextPage()}>{s.more}</Button>} />
      <input hidden ref={input} type="file" multiple accept=".md,.markdown,.txt" onChange={e => { const files = Array.from(e.target.files || []); e.target.value = ""; if (files.length) void importFiles(files); }} />
    </aside>}
    {!focus && <div {...sidebar.handleProps} className={cn(sidebar.handleProps.className, "notes-resize")} />}
    {selected.data ? <NoteDocument key={`${workspace.id}:${selected.data.id}`} note={selected.data} controller={controller} focus={focus} onFocus={() => setFocus(!focus)} /> : <main className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 p-8 text-center"><BookOpen size={28} className="text-muted-foreground" /><h2 className="text-lg font-medium">{selected.isError ? s.unavailable : id ? s.loading : s.empty}</h2><p className="max-w-sm text-sm leading-relaxed text-muted-foreground">{!id && s.emptyHint}</p>{(!id || selected.isError) && <Button onClick={() => void add()}><Plus size={15} />{s.new}</Button>}</main>}
  </div>;
}

/** 保存状态的四个取值。图标和文案都按它查表 —— 它们是同一件事的两面,不该各写一遍四分支。 */
type NoteStatus = "saved" | "saving" | "draft" | "error";
const STATUS_ICON = { saved: Check, saving: Loader2, draft: PenLine, error: AlertCircle } as const;

function NoteStatusBadge({ status, label }: { status: NoteStatus; label: string }) {
  const Icon = STATUS_ICON[status];
  return <span className="note-status" role="status" data-state={status}>
    <Icon size={12} className={status === "saving" ? "animate-mosael-spin" : undefined} aria-hidden="true" />{label}
  </span>;
}

export function NoteDocument({ note, controller, focus, onFocus }: { note: Note; controller: React.MutableRefObject<NoteController | null>; focus: boolean; onFocus: () => void }) {
  const s = useNoteStrings(); const qc = useQueryClient();
  const storageKey = `mosael.note.draft.${note.workspace_id}.${note.id}`;
  const [draft, setDraft] = React.useState<Note>(() => { try { const cached = JSON.parse(localStorage.getItem(storageKey) || "null") as Note | null; return cached?.id === note.id && cached.workspace_id === note.workspace_id ? cached : note; } catch { return note; } });
  const latest = React.useRef(draft); latest.current = draft;
  const saved = React.useRef(JSON.stringify(note)); const busy = React.useRef(false); const mounted = React.useRef(true);
  const [status, setStatus] = React.useState<NoteStatus>(JSON.stringify(draft) === JSON.stringify(note) ? "saved" : "draft"); const [error, setError] = React.useState("");
  const [moreOpen, setMoreOpen] = React.useState(false);
  const [mode, setMode] = React.useState("edit"); const [properties, setProperties] = React.useState(false);
  const [history, setHistory] = React.useState(false);
  const [referenceRevision,setReferenceRevision] = React.useState<number | null>(null);
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
    } catch (e) { if (request === historyRequest.current) toast.error(errorText(e)); }
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
    } catch (e) { if (mounted.current) { setError(e instanceof ApiError && e.status === 409 ? s.conflict : errorText(e)); setStatus("error"); } }
    finally { busy.current = false; }
  }, [note.id, note.workspace_id, qc, s.conflict, storageKey]);
  React.useLayoutEffect(() => {
    const current: NoteController = {id:note.id,read:()=>latest.current,update:async patch=>{
      change(patch);
      while(busy.current)await new Promise(resolve=>setTimeout(resolve,20));
      await persist();
      if(JSON.stringify(latest.current)!==saved.current)throw new Error(s.conflict);
      return latest.current;
    }};
    controller.current = current;
    return () => { if(controller.current===current)controller.current=null; };
  });
  /**
   * 后台往这篇文档追加了内容(逐字稿/字幕导出、智能体写入)时,把那一段并进当前草稿,
   * 而不是等下一次自动保存撞 409、再让用户去点「重新载入」。
   *
   * 合并本身是纯函数(`mergeAppendedNote`),它也负责判断这次改动到底算不算一次追加;
   * 这里只做副作用:落草稿、对齐修订号、把状态从冲突里放出来。
   */
  React.useEffect(() => {
    if (busy.current) return;
    const known = JSON.parse(saved.current) as Note;
    // 服务端有了更新的一版、而这里没有没存的改动:整份跟上。此前只认「追加」这一种,于是别处
    // 把它移进回收站、改了收藏,这里永远看不到,下一次自动保存还会拿旧修订号撞冲突。
    if (note.revision > known.revision && JSON.stringify(latest.current) === saved.current) {
      saved.current = JSON.stringify(note); latest.current = note; setDraft(note); setError(""); setStatus("saved");
      localStorage.removeItem(storageKey);
      return;
    }
    const merged = mergeAppendedNote(known, note, latest.current);
    if (!merged) return;
    // 服务端那一版就是新的比较基准:下一次自动保存据此判断"还有没有没存的改动"。
    saved.current = JSON.stringify(note);
    const settled = JSON.stringify(merged) === saved.current;
    latest.current = merged; setDraft(merged); setError(""); setStatus(settled ? "saved" : "draft");
    if (settled) localStorage.removeItem(storageKey);
    else { try { localStorage.setItem(storageKey, JSON.stringify(merged)); } catch { /* 草稿仍在内存里。 */ } }
  }, [note, status, storageKey]);
  React.useEffect(() => { if (status === "error") return; const timer = setTimeout(() => void persist(), 700); return () => clearTimeout(timer); }, [draft, status, persist]);
  React.useEffect(() => { mounted.current = true; const unload = (e: BeforeUnloadEvent) => { if (JSON.stringify(latest.current) !== saved.current) { e.preventDefault(); e.returnValue = ""; } }; window.addEventListener("beforeunload", unload); return () => { mounted.current = false; window.removeEventListener("beforeunload", unload); void persist(); }; }, [persist]);
  React.useEffect(() => {
    const readRevision = () => {
      const params = new URLSearchParams(window.location.hash.split("?")[1]);
      if (params.get("note") !== note.id) return;
      const revision = Number(params.get("revision"));
      setReferenceRevision(Number.isSafeInteger(revision)&&revision>0?revision:null);
    };
    readRevision(); window.addEventListener("hashchange", readRevision);
    return () => window.removeEventListener("hashchange", readRevision);
  }, [note.id]);
  async function restore() { if (!historic || busy.current) return; await persist(); if (JSON.stringify(latest.current) !== saved.current) return; try { const next = await api<Note>(`/api/notes/${note.id}/restore`, {method: "POST", body: JSON.stringify({workspace_id: note.workspace_id, base_revision: latest.current.revision, revision: historic.revision})}); saved.current = JSON.stringify(next); latest.current = next; setDraft(next); setHistoric(null); setHistory(false); setStatus("saved"); localStorage.removeItem(storageKey); qc.setQueryData(["note", note.workspace_id, note.id], next); void qc.invalidateQueries({queryKey: ["notes", note.workspace_id]}); } catch (e) { toast.error(errorText(e)); } }
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
    } catch (e) { toast.error(errorText(e)); setDeleting(false); }
  }
  const [toolbarTarget, setToolbarTarget] = React.useState<HTMLDivElement | null>(null);
  return <><main className="note-document"><header className="note-document-header"><button className="note-icon" aria-label={focus ? s.exitFocus : s.focus} title={focus ? s.exitFocus : s.focus} onClick={onFocus}>{focus ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}</button>
      <div className="note-header-format" ref={setToolbarTarget} />
      {/* 右边一组:保存状态 → 看的方式 → 收藏 → 更多。保存状态说的是「这篇文档」,和格式工具不是一类,
          夹在收起按钮和格式工具之间时像是格式工具的一部分。 */}
      <div className="note-header-actions"><NoteStatusBadge status={status} label={s[status]} />
      <div className="note-modes" role="group" aria-label={s.viewMode}>{(["edit", "read", "raw"] as const).map((m, i) => <button key={m} className="note-mode" aria-pressed={mode === m} onClick={() => setMode(m)}>{[s.write, s.preview, s.raw][i]}</button>)}</div>
      <button className="note-icon" aria-label={s.favorite} aria-pressed={draft.favorite} onClick={() => change({favorite: !draft.favorite})}><Star size={15} fill={draft.favorite ? "currentColor" : "none"} /></button>
      <Popover open={moreOpen} onOpenChange={setMoreOpen}><PopoverTrigger asChild><button className="note-icon" aria-label={s.actions} title={s.actions}><MoreHorizontal size={18}/></button></PopoverTrigger>{/* 和笔记列表的右键菜单同一套尺寸与条目样式(components/ui/floating 的 MENU_ITEM)。 */}
      <PopoverContent className="grid w-auto min-w-48 gap-0.5 p-1.5" align="end">
        <button type="button" className={cn(MENU_ITEM, "w-full text-left")} onClick={() => { setMoreOpen(false); exportMarkdown(draft); }}><Download />{s.export}</button>
        <button type="button" className={cn(MENU_ITEM, "w-full text-left")} onClick={() => { setMoreOpen(false); setHistory(true); }}><History />{s.history}</button>
        <button type="button" className={cn(MENU_ITEM, "w-full text-left")} onClick={() => { setMoreOpen(false); setProperties(!properties); }}><Info />{s.source}</button>
        <div className={MENU_SEPARATOR} role="separator" />
        <button type="button" className={cn(MENU_ITEM, "w-full text-left", !draft.trashed && "hover:text-destructive focus:text-destructive")} onClick={() => { setMoreOpen(false); change({trashed: !draft.trashed}); }}>{draft.trashed ? <RotateCcw /> : <Trash2 />}{draft.trashed ? s.restoreTrash : s.moveTrash}</button>
      </PopoverContent></Popover>
    </div></header>{draft.trashed && <div className="note-trash-notice" role="status"><div className="note-notice-row"><span>{s.inTrash}</span><span className="note-notice-actions"><button onClick={() => change({trashed: false})}><RotateCcw size={13} aria-hidden="true" />{s.restoreTrash}</button><button className="note-notice-danger" disabled={deleting} onClick={() => setConfirmDelete(true)}><Trash2 size={13} aria-hidden="true" />{s.deleteForever}</button></span></div></div>}{error && <div className="note-error-notice" role="alert"><div className="note-notice-row"><span><AlertCircle size={13} aria-hidden="true"/>{error}</span><button onClick={() => void persist()}>{s.retry}</button><button onClick={() => { exportMarkdown(draft); void getNote(note.workspace_id, note.id).then(n => { saved.current = JSON.stringify(n); latest.current = n; setDraft(n); setStatus("saved"); setError(""); localStorage.removeItem(storageKey); }).catch(e => toast.error(errorText(e))); }}>{s.reload}</button></div></div>}
    {referenceRevision&&<div className="note-reference-notice"><div className="note-notice-row"><span>{s.referenceVersion(referenceRevision)}</span><button onClick={()=>{setHistory(true);void loadVersion(referenceRevision);}}>{s.viewReference}</button></div></div>}
    <div className="note-body"><article className="note-paper">
      {mode === "raw" ? <><textarea aria-label={s.title} className="note-title" rows={1} placeholder={s.untitled} value={draft.title} maxLength={240} disabled={draft.trashed} onChange={e => change({title: e.target.value})} /><textarea className="note-raw" rows={1} spellCheck={false} maxLength={500000} aria-label={s.content} value={draft.markdown} disabled={draft.trashed} onChange={e => change({markdown: e.target.value})} /></> : <NoteEditor key={mode} toolbarTarget={toolbarTarget} markdown={draft.markdown} onChange={markdown => change({markdown})} editable={mode === "edit" && !draft.trashed} workspaceId={note.workspace_id} noteId={note.id}
        title={<textarea aria-label={s.title} className="note-title" rows={1} placeholder={s.untitled} value={draft.title} maxLength={240} disabled={draft.trashed || mode === "read"} onChange={e => change({title: e.target.value})} />}
        onReference={n => { if (!latest.current.sources.some(source => source.kind === "note" && source.id === n.id && source.revision === n.revision)) change({sources: [...latest.current.sources, {kind: "note", id: n.id, label: n.title, quote: "", revision: n.revision}]}); }} />}
    </article></div></main>
    {properties && <aside className="note-properties"><header><strong>{s.source}</strong><button className="note-icon" aria-label={s.close} onClick={()=>setProperties(false)}><X size={15}/></button></header><label>{s.topics}</label><NoteLabels label={s.topics} placeholder={s.topicHint} values={draft.topics} disabled={draft.trashed} onChange={topics=>change({topics})}/><label>{s.tags}</label><NoteLabels label={s.tags} placeholder={s.tagHint} values={draft.tags} disabled={draft.trashed} onChange={tags=>change({tags})}/><label>{s.source}</label>{draft.sources.length ? draft.sources.map((source, i) => <div className="note-source" key={i}><SourceLink source={source} workspaceId={note.workspace_id} />{source.quote && <blockquote>{source.quote}</blockquote>}</div>) : <p className="leading-relaxed text-muted-foreground">{s.sourcesEmpty}</p>}</aside>}
    <ConfirmDialog open={confirmDelete} title={`${s.deleteForever} · ${draft.title || s.untitled}`} body={s.deleteWarning} onCancel={() => { if (!deleting) setConfirmDelete(false); }} pending={deleting} onConfirm={() => void deleteForever()} />
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

function NoteLabels({label,placeholder,values,disabled,onChange}: {label:string;placeholder:string;values:string[];disabled:boolean;onChange:(values:string[])=>void}) {
  const value = values.join(", ");
  const [text,setText] = React.useState(value);
  React.useEffect(()=>setText(value),[value]);
  const commit = () => { const next = [...new Set(text.split(/[,，]/).map(v=>v.trim()).filter(Boolean))]; if (next.join(", ") !== value) onChange(next); setText(next.join(", ")); };
  return <Input aria-label={label} placeholder={placeholder} value={text} disabled={disabled} onChange={e=>setText(e.target.value)} onBlur={commit} onKeyDown={e=>{if(e.key==='Enter')e.currentTarget.blur();}}/>;
}
