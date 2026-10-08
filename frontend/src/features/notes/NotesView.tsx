import React from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, BookOpen, Bot, CheckSquare, SearchX, MoreHorizontal, Check, FileCode, Loader2, PenLine, X, Plus, Star, FileOutput, Import, PanelLeftClose, PanelLeftOpen, History, Info, TextQuote, Trash2, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import type { Workspace } from "@/api/client";
import { ApiError } from "@/api/transport";
import { PageLoadError } from "@/components/layout/EmptyState";
import {
  createNote,
  getNote,
  listNotes,
  listNoteTopics,
  purgeNote,
  restoreNoteRevision,
  saveNote,
  type Note,
  type NoteContent,
} from "@/api/domains/notes";
import { noteKeys } from "@/api/queryKeys";
import { noteHref, openNote } from "@/lib/deepLink";
import { errorText } from "@/api/errorMessage";
import { ConfirmDialog } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { DraftTextarea } from "@/components/ui/draft-text";
import { Input } from "@/components/ui/input";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { Popover, PopoverTrigger } from "@/components/ui/popover";
import { IconButton } from "@/components/ui/icon-button";
import { MenuContent, MenuItem, MenuSeparator } from "@/components/ui/menu";
import { Hint } from "@/components/ui/tooltip";
import { saveBlobToDisk } from "@/lib/download";
import { useFileDrop } from "@/lib/useFileDrop";
import { useWriteBlocked, type WriteBlock } from "@/components/layout/useWriteBlocked";
import { SIDEBAR_HANDLE_CLASS, handleOffset, useResizableSidebar } from "@/lib/useResizableSidebar";
import { useI18n } from "@/app/preferences";
import type { ComposerChip } from "@/lib/composerChip";
import { plainExcerpt } from "@/lib/plainExcerpt";
import type { AgentMessageQuote } from "@/api/domains/sessions";
import { noteAgentContext } from "./noteAgentContext";
import { NoteHistoryDialog } from "./NoteHistoryDialog";
import type { NoteSelection } from "./noteSelection";
import type { NoteAiAction } from "./NoteSelectionToolbar";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";
import { NoteEditor } from "./NoteEditor";
import { SourceLink } from "./NoteSources";
import { useNoteStrings } from "./strings";
import { NoteList, type NoteListAction } from "./NoteList";
import { mergeAppendedNote } from "./appendMerge";
import { isImeKeystroke } from "@/lib/shortcuts";
import { useSaveShortcut } from "@/lib/saveShortcut";
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
const NOTE_FILTERS = ["all", "favorite", "trash"] as const;
/** 停靠助手时给正文留的最小宽度;放不下就改成盖在正文上(和剪辑页同一个做法)。 */
const NOTE_MIN_WIDTH = 480;
/** 助手开着时多久重取一次打开着的那篇:智能体直接写的(append_note 不走确认卡)也要实时看得到。 */
const NOTE_FOLLOW_MS = 3000;
const selectionKey = (selection: NoteSelection) => `${selection.start}:${selection.end}:${selection.text}`;
type AgentMode = "docked" | "floating";
type PageOutbox = { id: number; text: string; context: string };
/** 哪些动作是「改这段」(结果用 edit_note 落回)、哪个是「接着写」(插在后面),其余只在对话里回答。 */
const REPLACE_ACTIONS: readonly NoteAiAction[] = ["polish", "rewrite", "expand", "shorten", "translate"];

/**
 * 笔记页的助手面板 —— 就是剪辑页、画板用的那一个(features/agent/CanvasAgentChat),**由页面装配层交进来**
 * (app/pages)。助手认识笔记(给消息挂笔记、把回复存成笔记),笔记这边再 import 助手就成了互相依赖
 * (见 features/featureBoundaries.test)。这里只写笔记页要给它的那几样。
 */
export interface NotesAgentPanelProps {
  /** 开着哪一篇(没开是 null):每一篇有自己的对话(ADR 0044),面板据此接那一篇的。 */
  noteId: string | null;
  contextLine: () => string;
  contextChips: ComposerChip[];
  /** 这条消息带着的选区摘录:落进消息,对话气泡里画成可点的一行(点了回到这篇、定位到这段)。 */
  messageQuote: AgentMessageQuote | null;
  focusSignal: number;
  /** 选区工具条上的 AI 动作投递给面板的那一条;面板接走时回调 onOutboxTaken,这里清掉。 */
  outbox: PageOutbox | null;
  onOutboxTaken: () => void;
  /** 一条消息发出去了:放下钉住的那段选区。 */
  onSent: () => void;
  emptyHint: string;
  placeholder: string;
  rectKey: string;
  dockedLayout: "inline" | "overlay";
  workspaceId: string;
  mode: AgentMode;
  onModeChange: (mode: AgentMode) => void;
  onClose: () => void;
}
const MARKDOWN_IMPORT_LIMIT = 500_000;
const isMarkdownFile = (file: File) => /\.(md|markdown|txt)$/i.test(file.name);
export function exportMarkdown(note: Pick<Note, "title" | "markdown" | "sources">) {
  const sources = note.sources.map(source => `- ${source.label || source.kind}${source.kind === "url" ? `: ${source.url}` : source.kind === "note" ? `: ${noteHref(source.id, source.revision)}` : ` [${source.kind}:${source.id}${source.start != null ? ` @ ${source.start}–${source.end ?? ""}s` : ""}]`}`).join("\n");
  const blob = new Blob([`# ${note.title}\n\n${note.markdown}${sources ? `\n\n---\n\n${sources}\n` : ""}`], { type: "text/markdown;charset=utf-8" });
  // 控制字符是故意的:这是文件名净化,\x00-\x1f 在各家文件系统上都非法,和 <>:"/\\|?* 一起替掉。
  // eslint-disable-next-line no-control-regex
  saveBlobToDisk(blob, `${(note.title || "note").replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").slice(0, 100)}.md`);
}

export function NotesView({ workspace, AgentPanel, onNoteChange }: {
  workspace: Workspace;
  AgentPanel?: React.ComponentType<NotesAgentPanelProps>;
  /** 开着哪一篇(打不开的那篇不算):装配层据此告诉助手「这一处是这篇笔记」(见 app/pages)。 */
  onNoteChange?: (noteId: string | null) => void;
}) {
  const s = useNoteStrings(); const qc = useQueryClient(); const t = useI18n();
  const writeBlocked = useWriteBlocked(workspace.role);
  const [id, setId] = React.useState(() => locationNote() ?? rememberedNote(workspace.id));
  // 从记住的那篇打开时把地址补上,和点开一篇的状态一样(刷新、返回都认它)。
  React.useEffect(() => { if (id && !locationNote()) window.history.replaceState(null, "", noteHref(id)); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  React.useEffect(() => { if (id) rememberNote(workspace.id, id); }, [workspace.id, id]);
  const sidebar = useResizableSidebar("notes", { min: 220, max: 480, fallback: 260 });
  const [selecting,setSelecting] = React.useState(false);
  const controller = React.useRef<NoteController | null>(null);

  const [q, setQ] = React.useState(""); const search = React.useDeferredValue(q);
  // 「全部 / 收藏 / 回收站」记住:切到别的页再回来还在原来那一栏(和上次打开的那篇一样)。
  const [filter, setFilter] = usePersistentTab("notes-filter", "all", NOTE_FILTERS); const [topic, setTopic] = React.useState("");
  const [focus, setFocus] = React.useState(() => !!locationNote() && window.matchMedia("(max-width: 740px)").matches); const input = React.useRef<HTMLInputElement>(null);
  React.useEffect(() => { const read = () => setId(locationNote()); window.addEventListener("hashchange", read); return () => window.removeEventListener("hashchange", read); }, []);
  //: 收藏 / 主题**交给服务端筛**,和分页同一层。此前拉回前 200 条再在这里筛:收藏排在 200 条之后时,
  //: 空态写着「还没有收藏」,底下却挂着「加载更多」;主题下拉也只列得出已加载那些笔记里的主题。
  const listFilter = { trashed: filter === "trash", favorite: filter === "favorite", topic };
  const notes = useInfiniteQuery({ queryKey: noteKeys.page(workspace.id, search, listFilter), initialPageParam: 0,
    queryFn: ({ pageParam }) => listNotes(workspace.id, search, listFilter, pageParam), getNextPageParam: (last, pages) => last.length === 200 ? pages.length * 200 : undefined });
  const shown = notes.data?.pages.flat() || [];
  const topics = useQuery({ queryKey: noteKeys.topics(workspace.id, filter === "trash"), queryFn: () => listNoteTopics(workspace.id, filter === "trash") }).data ?? [];
  // 打开一篇就重新取一次(staleTime 0):缓存里的那份可能是移进回收站、收藏之前的,打开后看到的
  // 就是错的状态 —— 回收站里的笔记没有提示条、还能编辑。
  //: 笔记页的助手:和剪辑页、画板**同一个面板**(CanvasAgentChat)。每一篇笔记有自己的对话(ADR 0044):换一篇就换成那一篇的,
  //: 没开哪篇时算 AI Studio —— 地方由装配层按 onNoteChange 登记。开合、停靠方式、宽度各记各的。
  const [agentOpen, setAgentOpen] = usePersistentTab<"on" | "off">("notes-agent", "off", ["on", "off"]);
  const [agentMode, setAgentMode] = usePersistentTab<AgentMode>("notes-agent-mode", "docked", ["docked", "floating"]);
  const agentPanel = useResizableSidebar("notes-agent", { min: 320, max: 640, fallback: 400 });
  const [layoutWidth, setLayoutWidth] = React.useState(Infinity);
  const measureLayout = React.useCallback((node: HTMLDivElement | null) => {
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => { if (entry.contentRect.width > 0) setLayoutWidth(entry.contentRect.width); });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const showAgent = agentOpen === "on" && !!AgentPanel;
  const dockedAgent = showAgent && agentMode === "docked" && layoutWidth >= (focus ? 0 : sidebar.width) + agentPanel.width + NOTE_MIN_WIDTH;
  //: 编辑器里的选区 / 光标(正文原文,见 noteSelection)。点了小条上的 × 就不再带这一段,直到选区变了。
  const [selection, setSelection] = React.useState<NoteSelection | null>(null);
  const [dismissed, setDismissed] = React.useState("");
  //: 「问 AI」「引用到对话」、AI 动作**钉住**的那一段:编辑器里的选区之后变了也还带着它,发出去(onSent)或点掉才放下。
  //: 没钉住时跟着编辑器里的选区走。
  const [pinned, setPinned] = React.useState<NoteSelection | null>(null);
  const live = selection && !(selection.text && selectionKey(selection) === dismissed) ? selection : null;
  const quoted = pinned ?? live;
  const [outbox, setOutbox] = React.useState<PageOutbox | null>(null);
  const outboxSeq = React.useRef(0);
  const quotedRef = React.useRef(quoted); quotedRef.current = quoted;
  const [focusSignal, setFocusSignal] = React.useState(0);
  React.useEffect(() => { setSelection(null); setDismissed(""); setPinned(null); setOutbox(null); }, [id]);
  //: 发送那一刻才拼:正文取编辑器里最新的草稿(controller),不是上次存盘的那份。
  const agentContext = React.useCallback(() => noteAgentContext(t, controller.current?.read() ?? null, quotedRef.current), [t]);
  const selectionChips: ComposerChip[] = quoted?.text ? [{
    id: "note-selection", label: plainExcerpt(quoted.text), icon: <TextQuote size={11} />,
    text: { title: t("noteAgentSelectionChip"), body: quoted.text },
    onRemove: () => { setPinned(null); setDismissed(selectionKey(quoted)); },
  }] : [];
  const askAi = (picked: NoteSelection) => { setPinned(picked); setAgentOpen("on"); setFocusSignal(n => n + 1); };
  //: 引用到对话:只挂小条,不发、不抢输入框焦点。
  const quoteInChat = (picked: NoteSelection) => { setPinned(picked); setAgentOpen("on"); };
  //: AI 快捷动作:钉住这段、打开面板、投递一条带动作说明的消息 —— 面板接到就发(见 CanvasAgentChat 的 outbox)。
  //: 改这段的(润色、翻译……)要求用 edit_note 落回:卡上有原文 → 新文的对照,批了才改、能撤销;总结、解释只回答。
  const aiAction = (action: NoteAiAction, picked: NoteSelection) => {
    const meta = s.selection.actions[action];
    const lang = /[\u3400-\u9fff]/.test(picked.text) ? s.selection.languages.en : s.selection.languages.zh;
    const goal = meta.hint;
    const key = REPLACE_ACTIONS.includes(action) ? "noteAgentActionReplace" : action === "continue" ? "noteAgentActionInsert" : "noteAgentActionAnswer";
    setPinned(picked);
    setAgentOpen("on");
    setOutbox({
      id: ++outboxSeq.current,
      text: meta.prompt.replace("{lang}", lang),
      context: t(key).replace("{action}", meta.label).replace("{goal}", action === "translate" ? `${goal} → ${lang}` : goal),
    });
  };
  const selected = useQuery({ queryKey: noteKeys.detail(workspace.id, id ?? ""), queryFn: () => getNote(workspace.id, id!), enabled: !!id, staleTime: 0,
    refetchInterval: showAgent ? NOTE_FOLLOW_MS : false });
  const openNoteId = id && !selected.isError ? id : null;
  React.useEffect(() => { onNoteChange?.(openNoteId); }, [openNoteId, onNoteChange]);
  //: 摘录最多存这么多字(后端上限 2000);定位靠它找回那一段,长了也只多占库。
  const messageQuote: AgentMessageQuote | null = quoted?.text && selected.data ? {
    kind: "note", note_id: selected.data.id, title: selected.data.title || s.untitled, text: quoted.text.slice(0, 2000), start: quoted.start,
  } : null;
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
          await purgeNote(workspace.id,current.id,current.save_seq);
          localStorage.removeItem(`mosael.note.draft.${workspace.id}.${current.id}`);
          qc.removeQueries({queryKey:noteKeys.detail(workspace.id,current.id)});
          qc.removeQueries({queryKey:noteKeys.history(current.id)});
        } else {
          const patch:Partial<NoteContent>=action==="rename"?{title:value||""}:action==="trash"||action==="restore"?{trashed:action==="trash"}:{favorite:action==="favorite"};
          const result=active?await active.update(patch):await saveNote({...current,...patch});
          qc.setQueryData(noteKeys.detail(workspace.id,current.id),result);
        }
        done.push(target.id);
      }catch(e){failed++;toast.error(errorText(e));}
    }
    await qc.invalidateQueries({queryKey:noteKeys.lists(workspace.id)});
    if(["trash","restore","delete"].includes(action)&&id&&done.includes(id)){rememberNote(workspace.id,null);window.location.hash="#/notes";}
    if(failed)toast.error(s.partialFailure(failed));
    return done;
  }
  async function add(markdown = "", title = "") { try { setFilter("all"); setQ(""); setTopic(""); const n = await createNote(workspace.id, { title, markdown }); void qc.invalidateQueries({ queryKey: noteKeys.lists(workspace.id) }); openNote(n.id); if (window.matchMedia("(max-width: 740px)").matches) setFocus(true); } catch (e) { toast.error(errorText(e)); } }
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
    void qc.invalidateQueries({ queryKey: noteKeys.lists(workspace.id) });
    if (last) openNote(last.id);
    const imported = accepted.length - failed.length;
    if (failed.length) toast.error(s.importPartial(imported, failed));
    else if (imported > 1) toast.success(s.imported(imported));
  }
  // 只拖图片/音视频时不接:那是往正文里插图(编辑器自己处理),不是导入笔记。
  const drop = useFileDrop(files => void importFiles(files), isMarkdownFile, types => types.some(type => !/^(image|video|audio)\//.test(type)));
  return <div ref={measureLayout} className={`notes-layout ${!focus ? "notes-show-list" : ""}`} {...(writeBlocked ? {} : drop.handlers)}>
    {drop.active && <div className="notes-drop" aria-hidden="true"><span><Import size={20} />{s.dropHint}</span></div>}
    {!focus && <aside className="notes-index" style={{ "--notes-index-width": `${sidebar.width}px` } as React.CSSProperties}><header><h1>{s.title}</h1><div className="flex shrink-0 items-center gap-1"><IconButton unstyled className="note-icon" label={s.import} disabled={Boolean(writeBlocked)} disabledReason={writeBlocked?.reason} onClick={() => input.current?.click()}><Import size={16} /></IconButton><IconButton unstyled className="note-icon" label={s.selectNotes} aria-pressed={selecting} onClick={()=>setSelecting(!selecting)}><CheckSquare size={16}/></IconButton><IconButton unstyled className="note-icon" label={s.new} disabled={Boolean(writeBlocked)} disabledReason={writeBlocked?.reason} onClick={() => void add()}><Plus size={16} /></IconButton></div></header>
      <Input aria-label={s.search} placeholder={s.search} value={q} onChange={e => setQ(e.target.value)} />
      <nav className="notes-filter">{([["all", s.all], ["favorite", s.favorite], ["trash", s.trash]] as const).map(([key, label]) => <button key={key} aria-pressed={filter === key} onClick={() => { setFilter(key); setTopic(""); window.location.hash = "#/notes"; }}>{label}</button>)}</nav>
      {!!topics.length && <SearchableSelect value={topic} onValueChange={setTopic} options={[{value: "", label: s.topics}, ...topics.map(t => ({value:t,label:t}))]} placeholder={s.topics} />}
      <NoteList key={`${workspace.id}:${search}:${filter}:${topic}`} notes={shown} currentId={id} selecting={selecting} onSelecting={setSelecting}
        onOpen={noteId=>{openNote(noteId);if(window.matchMedia("(max-width: 740px)").matches)setFocus(true);}}
        onAction={listAction} writeBlocked={writeBlocked} empty={notes.isError?<PageLoadError size="compact" icon={<BookOpen size={15} />} error={notes.error} onRetry={() => void notes.refetch()} />:notes.isPending?<p className="p-3 text-xs text-muted-foreground">{s.loading}</p>:<div className="note-empty-state"><span className="note-empty-icon">{search || topic ? <SearchX size={24} strokeWidth={1.5} /> : filter === "trash" ? <Trash2 size={24} strokeWidth={1.5} /> : filter === "favorite" ? <Star size={24} strokeWidth={1.5} /> : <BookOpen size={24} strokeWidth={1.5} />}</span><strong>{search || topic ? s.noResults : filter === "trash" ? s.trashEmpty : filter === "favorite" ? s.favoriteEmpty : s.listEmpty}</strong><p>{search || topic ? s.searchHint : filter === "trash" ? s.trashHint : filter === "favorite" ? s.favoriteHint : s.listEmptyHint}</p>{search || topic ? <Button variant="ghost" size="sm" onClick={() => { setQ(""); setTopic(""); }}>{s.clearSearch}</Button> : filter === "all" ? <Hint disabledReason={writeBlocked?.reason}><Button variant="ghost" size="sm" disabled={Boolean(writeBlocked)} onClick={() => void add()}><Plus size={14} />{s.new}</Button></Hint> : null}</div>} more={notes.hasNextPage&&<Button variant="ghost" onClick={()=>void notes.fetchNextPage()}>{s.more}</Button>} />
      <input hidden ref={input} type="file" multiple accept=".md,.markdown,.txt" onChange={e => { const files = Array.from(e.target.files || []); e.target.value = ""; if (files.length) void importFiles(files); }} />
    </aside>}
    {!focus && <div {...sidebar.handleProps} className={cn(sidebar.handleProps.className, "notes-resize")} />}
    {selected.data ? <NoteDocument key={`${workspace.id}:${selected.data.id}`} note={selected.data} readOnly={writeBlocked} controller={controller} focus={focus} onFocus={() => setFocus(!focus)}
      agentOpen={showAgent} onToggleAgent={AgentPanel && (() => setAgentOpen(agentOpen === "on" ? "off" : "on"))} onSelectionChange={setSelection} onAskAi={AgentPanel && askAi}
      onAiAction={AgentPanel && aiAction} onQuote={AgentPanel && quoteInChat} /> : <main className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 p-8 text-center"><BookOpen size={28} className="text-muted-foreground" /><h2 className="text-lg font-medium">{selected.isError ? s.unavailable : id ? s.loading : s.empty}</h2><p className="max-w-sm text-sm leading-relaxed text-muted-foreground">{!id && s.emptyHint}</p>{(!id || selected.isError) && <Hint disabledReason={writeBlocked?.reason}><Button disabled={Boolean(writeBlocked)} onClick={() => void add()}><Plus size={15} />{s.new}</Button></Hint>}</main>}
    {showAgent && (
      // 停靠:占一栏,正文真的让出宽度。放不下时改成盖在正文右侧;浮动时面板自己 fixed,外层 contents 不占位。
      <div data-testid="notes-agent-slot"
        className={dockedAgent ? "grid min-h-0 min-w-0 grid-cols-[minmax(0,1fr)] border-l border-divider" : agentMode === "docked" ? "absolute bottom-2 right-2 top-2 z-40 grid w-[min(400px,90%)] grid-cols-[minmax(0,1fr)]" : "contents"}
        style={dockedAgent ? { flex: `0 0 ${agentPanel.width}px` } : undefined}>
        <React.Suspense fallback={null}><AgentPanel
          noteId={openNoteId}
          contextLine={agentContext}
          contextChips={selectionChips}
          messageQuote={messageQuote}
          focusSignal={focusSignal}
          outbox={outbox}
          onOutboxTaken={() => setOutbox(null)}
          onSent={() => setPinned(null)}
          emptyHint={t("noteAgentEmpty")}
          placeholder={t("noteAgentPlaceholder")}
          rectKey="mosael.notes.agent.rect.v1"
          dockedLayout={dockedAgent ? "inline" : "overlay"}
          workspaceId={workspace.id}
          mode={agentMode}
          onModeChange={setAgentMode}
          onClose={() => setAgentOpen("off")}
        /></React.Suspense>
      </div>
    )}
    {dockedAgent && <div className={SIDEBAR_HANDLE_CLASS} style={{ right: handleOffset(agentPanel.width) }} role="separator" aria-orientation="vertical" onPointerDown={agentPanel.startDragFromRight} />}
  </div>;
}

/** 保存状态的四个取值。图标和文案都按它查表 —— 它们是同一件事的两面,不该各写一遍四分支。 */
type NoteStatus = "saved" | "saving" | "draft" | "error";
const STATUS_ICON = { saved: Check, saving: Loader2, draft: PenLine, error: AlertCircle } as const;

/** 保存状态:一块定宽的位置(「保存中」「已保存」换来换去时不推着右边的按钮动),颜色比按钮弱一档;
 *  窄了只剩图标,悬停说明里还有一份文字。 */
function NoteStatusBadge({ status, label }: { status: NoteStatus; label: string }) {
  const Icon = STATUS_ICON[status];
  return <Hint label={label}><span className="note-status" role="status" data-slot="save-status" data-state={status}>
    <Icon size={12} className={status === "saving" ? "animate-mosael-spin" : undefined} aria-hidden="true" /><span className="note-status-label">{label}</span>
  </span></Hint>;
}

export function NoteDocument({ note, readOnly = null, controller, focus, onFocus, agentOpen = false, onToggleAgent, onSelectionChange, onAskAi, onAiAction, onQuote }: {
  note: Note;
  /** 只读成员:正文、标题、主题和标签都不能改,收藏、移到回收站、恢复版本收成灰的(说明为什么)—— 否则打的字存不上、只换来一条报错。 */
  readOnly?: WriteBlock | null;
  controller: React.MutableRefObject<NoteController | null>; focus: boolean; onFocus: () => void;
  /** 笔记页助手的开关(顶栏右边那一组里);不给就不显示。 */
  agentOpen?: boolean; onToggleAgent?: () => void;
  onSelectionChange?: (selection: NoteSelection | null) => void; onAskAi?: (selection: NoteSelection) => void;
  onAiAction?: (action: NoteAiAction, selection: NoteSelection) => void; onQuote?: (selection: NoteSelection) => void;
}) {
  const s = useNoteStrings(); const qc = useQueryClient(); const t = useI18n();
  const storageKey = `mosael.note.draft.${note.workspace_id}.${note.id}`;
  const [draft, setDraft] = React.useState<Note>(() => { try { const cached = JSON.parse(localStorage.getItem(storageKey) || "null") as Note | null; return cached?.id === note.id && cached.workspace_id === note.workspace_id ? cached : note; } catch { return note; } });
  const latest = React.useRef(draft); latest.current = draft;
  const saved = React.useRef(JSON.stringify(note)); const busy = React.useRef(false); const mounted = React.useRef(true);
  const [status, setStatus] = React.useState<NoteStatus>(JSON.stringify(draft) === JSON.stringify(note) ? "saved" : "draft"); const [error, setError] = React.useState("");
  const [moreOpen, setMoreOpen] = React.useState(false);
  //: 两种看法:编辑(所见即所得)和 Markdown 源码。没有单独的「阅读」—— 只读的版本记录预览、画板上的文档格用的是
  //: NoteReader,那是另一个组件。
  const [mode, setMode] = React.useState<"edit" | "raw">("edit"); const [properties, setProperties] = React.useState(false);
  //: 换了看的方式,编辑器重建、选区没了 —— 助手那边也别再带着上一个模式里的那段。
  React.useEffect(() => { onSelectionChange?.(null); }, [mode, onSelectionChange]);
  const [history, setHistory] = React.useState(false);
  //: 版本记录打开时选中哪一版:「查看引用版本」进来的是引用的那一版,从菜单进来的是当前版本。
  const [historyFocus, setHistoryFocus] = React.useState<number | null>(null);
  const [referenceRevision,setReferenceRevision] = React.useState<number | null>(null);
  const [confirmDelete, setConfirmDelete] = React.useState(false); const [deleting, setDeleting] = React.useState(false);
  //: 在回收站里的和只读成员看的,正文都不能改
  const locked = draft.trashed || Boolean(readOnly);
  function change(patch: Partial<NoteContent>) { const next = {...latest.current, ...patch}; latest.current = next; try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* Server autosave remains available when device storage is full. */ } setDraft(next); setStatus("draft"); }
  const persist = React.useCallback(async () => {
    if (busy.current || JSON.stringify(latest.current) === saved.current) return;
    busy.current = true; if (mounted.current) setStatus("saving"); const sent = latest.current;
    try { const result = await saveNote(sent); saved.current = JSON.stringify(result);
      const current = latest.current; const next = current === sent ? result : {...current, revision: result.revision, save_seq: result.save_seq, updated_at: result.updated_at}; latest.current = next;
      if (current === sent) localStorage.removeItem(storageKey); else { try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* Keep the live draft. */ } }
      if (mounted.current) { setDraft(next); setStatus(current === sent ? "saved" : "draft"); setError(""); }
      qc.setQueryData(noteKeys.detail(note.workspace_id, note.id), result); void qc.invalidateQueries({queryKey: noteKeys.lists(note.workspace_id)});
    } catch (e) { if (mounted.current) { setError(e instanceof ApiError && e.status === 409 ? s.conflict : errorText(e)); setStatus("error"); } }
    finally { busy.current = false; }
  }, [note.id, note.workspace_id, qc, s.conflict, storageKey]);
  //: ⌘S:欠着的这一份马上存,不等那 700ms(见 lib/saveShortcut)。
  useSaveShortcut(() => void persist());
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
    // 服务端有了更新的一份、而这里没有没存的改动:整份跟上。此前只认「追加」这一种,于是别处
    // 把它移进回收站、改了收藏,这里永远看不到,下一次自动保存还会拿旧的保存序号撞冲突。
    if (note.save_seq > known.save_seq && JSON.stringify(latest.current) === saved.current) {
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
  async function restore(revision: number) { if (busy.current) return; await persist(); if (JSON.stringify(latest.current) !== saved.current) return; try { const next = await restoreNoteRevision(note.workspace_id, note.id, latest.current.save_seq, revision); saved.current = JSON.stringify(next); latest.current = next; setDraft(next); setHistory(false); setStatus("saved"); localStorage.removeItem(storageKey); qc.setQueryData(noteKeys.detail(note.workspace_id, note.id), next); void qc.invalidateQueries({queryKey: noteKeys.lists(note.workspace_id)}); } catch (e) { toast.error(errorText(e)); } }
  async function deleteForever() {
    if (deleting || busy.current) return;
    await persist();
    if (JSON.stringify(latest.current) !== saved.current) return;
    setDeleting(true);
    try {
      await purgeNote(note.workspace_id, note.id, latest.current.save_seq);
      localStorage.removeItem(storageKey);
      window.location.hash = "#/notes";
      qc.removeQueries({queryKey:noteKeys.detail(note.workspace_id, note.id)});
      qc.removeQueries({queryKey:noteKeys.history(note.id)});
      void qc.invalidateQueries({queryKey:noteKeys.lists(note.workspace_id)});
    } catch (e) { toast.error(errorText(e)); setDeleting(false); }
  }
  const [toolbarTarget, setToolbarTarget] = React.useState<HTMLDivElement | null>(null);
  return <><main className="note-document"><header className="note-document-header"><IconButton unstyled className="note-icon" label={focus ? s.exitFocus : s.focus} onClick={onFocus}>{focus ? <PanelLeftOpen size={16} strokeWidth={1.7} /> : <PanelLeftClose size={16} strokeWidth={1.7} />}</IconButton>
      <div className="note-header-format" ref={setToolbarTarget} />
      {/* 右边一组是文档级的:保存状态 → Markdown → AI 助手 → 收藏 → 更多。保存状态说的是「这篇文档」,和格式工具不是一类,
          夹在收起按钮和格式工具之间时像是格式工具的一部分。图标和左边格式按钮同一个规格(16、描边 1.7)。 */}
      <div className="note-header-actions"><NoteStatusBadge status={status} label={s[status]} />
      {/* Markdown 只剩一个选项:一颗能按下的切换(按下看源码,再点回到编辑)。 */}
      <IconButton unstyled className="note-icon note-source-toggle" label={s.raw} hint={s.rawHint} aria-pressed={mode === "raw"} onClick={() => setMode(mode === "raw" ? "edit" : "raw")}><FileCode size={16} strokeWidth={1.7} aria-hidden="true" /></IconButton>
      {/* 窄了只剩图标(文字收起),名字靠 IconButton 的 aria-label 和悬停说明。 */}
      {onToggleAgent && <IconButton unstyled className="note-agent-toggle" label={t("wfAgentTitle")} aria-pressed={agentOpen} onClick={onToggleAgent}><Bot size={16} strokeWidth={1.7} aria-hidden="true" /><span>{t("wfAgentTitle")}</span></IconButton>}
      <IconButton unstyled className="note-icon" label={s.favorite} aria-pressed={draft.favorite} disabled={Boolean(readOnly)} disabledReason={readOnly?.reason} onClick={() => change({favorite: !draft.favorite})}><Star size={16} strokeWidth={1.7} fill={draft.favorite ? "currentColor" : "none"} /></IconButton>
      <Popover open={moreOpen} onOpenChange={setMoreOpen}><PopoverTrigger asChild><IconButton unstyled className="note-icon" label={s.actions} aria-haspopup="menu"><MoreHorizontal size={16} strokeWidth={1.7} /></IconButton></PopoverTrigger>{/* 和笔记列表的右键菜单同一套条目(MenuItem / MenuItemBody)。 */}
      <MenuContent label={s.actions} align="end">
        <MenuItem icon={<FileOutput />} label={s.export} onClick={() => { setMoreOpen(false); exportMarkdown(draft); }} />
        <MenuItem icon={<History />} label={s.history} onClick={() => { setMoreOpen(false); setHistoryFocus(null); setHistory(true); }} />
        <MenuItem icon={<Info />} label={s.source} onClick={() => { setMoreOpen(false); setProperties(!properties); }} />
        <MenuSeparator />
        <MenuItem icon={draft.trashed ? <RotateCcw /> : <Trash2 />} label={draft.trashed ? s.restoreTrash : s.moveTrash} destructive={!draft.trashed} disabled={Boolean(readOnly)} description={readOnly?.brief} onClick={() => { setMoreOpen(false); change({trashed: !draft.trashed}); }} />
      </MenuContent></Popover>
    </div></header>{draft.trashed && <div className="note-trash-notice" role="status"><div className="note-notice-row"><span>{s.inTrash}</span><span className="note-notice-actions"><button disabled={Boolean(readOnly)} onClick={() => change({trashed: false})}><RotateCcw size={13} aria-hidden="true" />{s.restoreTrash}</button><button className="note-notice-danger" disabled={deleting || Boolean(readOnly)} onClick={() => setConfirmDelete(true)}><Trash2 size={13} aria-hidden="true" />{s.deleteForever}</button></span></div></div>}{error && <div className="note-error-notice" role="alert"><div className="note-notice-row"><span><AlertCircle size={13} aria-hidden="true"/>{error}</span><button onClick={() => void persist()}>{s.retry}</button><button onClick={() => { exportMarkdown(draft); void getNote(note.workspace_id, note.id).then(n => { saved.current = JSON.stringify(n); latest.current = n; setDraft(n); setStatus("saved"); setError(""); localStorage.removeItem(storageKey); }).catch(e => toast.error(errorText(e))); }}>{s.reload}</button></div></div>}
    {referenceRevision&&<div className="note-reference-notice"><div className="note-notice-row"><span>{s.referenceVersion(referenceRevision)}</span><button onClick={()=>{setHistoryFocus(referenceRevision);setHistory(true);}}>{s.viewReference}</button></div></div>}
    <div className="note-body"><article className="note-paper">
      {mode === "raw" ? <><DraftTextarea aria-label={s.title} className="note-title" rows={1} placeholder={s.untitled} value={draft.title} maxLength={240} disabled={locked} onValueChange={title => change({title})} /><textarea className="note-raw" rows={1} spellCheck={false} maxLength={500000} aria-label={s.content} value={draft.markdown} disabled={locked} onChange={e => change({markdown: e.target.value})} /></> : <NoteEditor toolbarTarget={toolbarTarget} markdown={draft.markdown} onChange={markdown => change({markdown})} editable={!locked} workspaceId={note.workspace_id} noteId={note.id}
        title={<DraftTextarea aria-label={s.title} className="note-title" rows={1} placeholder={s.untitled} value={draft.title} maxLength={240} disabled={locked} onValueChange={title => change({title})} />}
        onReference={n => { if (!latest.current.sources.some(source => source.kind === "note" && source.id === n.id && source.revision === n.revision)) change({sources: [...latest.current.sources, {kind: "note", id: n.id, label: n.title, quote: "", revision: n.revision}]}); }}
        onSelectionChange={onSelectionChange} onAskAi={onAskAi} onAiAction={onAiAction} onQuote={onQuote}
        saveSource={{ kind: "note", id: note.id, label: draft.title || s.untitled, quote: "", revision: draft.revision }} />}
    </article></div></main>
    {properties && <aside className="note-properties"><header><strong>{s.source}</strong><IconButton unstyled className="note-icon" label={s.close} onClick={()=>setProperties(false)}><X size={15}/></IconButton></header><label>{s.topics}</label><NoteLabels label={s.topics} placeholder={s.topicHint} values={draft.topics} disabled={locked} onChange={topics=>change({topics})}/><label>{s.tags}</label><NoteLabels label={s.tags} placeholder={s.tagHint} values={draft.tags} disabled={locked} onChange={tags=>change({tags})}/><label>{s.source}</label>{draft.sources.length ? draft.sources.map((source, i) => <div className="note-source" key={i}><SourceLink source={source} workspaceId={note.workspace_id} />{source.quote && <blockquote>{source.quote}</blockquote>}</div>) : <p className="leading-relaxed text-muted-foreground">{s.sourcesEmpty}</p>}</aside>}
    <ConfirmDialog open={confirmDelete} title={`${s.deleteForever} · ${draft.title || s.untitled}`} body={s.deleteWarning} onCancel={() => { if (!deleting) setConfirmDelete(false); }} pending={deleting} onConfirm={() => void deleteForever()} />
    <NoteHistoryDialog open={history} onOpenChange={setHistory} workspaceId={note.workspace_id} noteId={note.id}
      current={{ revision: draft.revision, saveSeq: draft.save_seq, title: draft.title, markdown: draft.markdown }} focusRevision={historyFocus} onRestore={restore} readOnly={readOnly} />
  </>;
}

function NoteLabels({label,placeholder,values,disabled,onChange}: {label:string;placeholder:string;values:string[];disabled:boolean;onChange:(values:string[])=>void}) {
  const value = values.join(", ");
  const [text,setText] = React.useState(value);
  React.useEffect(()=>setText(value),[value]);
  const commit = () => { const next = [...new Set(text.split(/[,，]/).map(v=>v.trim()).filter(Boolean))]; if (next.join(", ") !== value) onChange(next); setText(next.join(", ")); };
  return <Input aria-label={label} placeholder={placeholder} value={text} disabled={disabled} onChange={e=>setText(e.target.value)} onBlur={commit} onKeyDown={e=>{if(e.key==='Enter'&&!isImeKeystroke(e))e.currentTarget.blur();}}/>;
}
