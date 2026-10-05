import { usePreferences } from "@/app/preferences";
import { createPortal } from "react-dom";
import { useEditor, EditorContent } from "@tiptap/react";
import Placeholder from "@tiptap/extension-placeholder";
import React from "react";
import { Selection } from "@tiptap/pm/state";
import { toast } from "sonner";
import { useNoteStrings } from "./strings";
import { noteExtensions, notePlaceholder } from "./editorExtensions";
import { RefSuggestion } from "@/components/app/refSuggestion";
import { useSuggestionMenu } from "@/components/app/suggestionMenu";
import { useExternalContent } from "@/components/app/useExternalContent";
import { listNotes, type Note } from "@/api/domains/notes";
import { noteHref } from "@/lib/deepLink";
import { importAsset } from "@/api/domains/assets";
import { errorText } from "@/api/errorMessage";
import type { NoteSource } from "@/api/domains/notes";
import { NoteSelectionToolbar, type NoteAiAction, type ToolbarKeys } from "./NoteSelectionToolbar";
import { useReadAloud } from "./readAloud";
import { SaveToNote } from "./SaveToNote";
import { AddToBoardDialog } from "./AddToBoardDialog";
import { InactiveSelection } from "./inactiveSelection";
import { findPassage, followMarkdown, readNoteSelection, type NoteSelection } from "./noteSelection";
import { NOTE_PASSAGE_EVENT, parseNotePassage, useOpenRequest } from "@/lib/deepLink";
import { NoteFormatToolbar } from "./NoteFormatToolbar";

export function NoteReader({ markdown }: { markdown: string }) {
  const { locale } = usePreferences();
  const editor = useEditor({ extensions: noteExtensions(true, locale), content: markdown, contentType: "markdown", editable: false,
    editorProps: { attributes: { class: "note-prose" } } });
  useExternalContent(editor, (instance) => { instance.commands.setContent(markdown, {contentType:"markdown", emitUpdate:false}); }, [markdown]);
  return <EditorContent editor={editor} />;
}

/** 选区停下来多久才报给笔记页(给助手的上下文)。拖着选的那一路不必每一步都算一遍。 */
const SELECTION_REPORT_MS = 150;

export function NoteEditor({ markdown, onChange, onReference, workspaceId, noteId, title, toolbarTarget, editable = true, onSelectionChange, onAskAi, onAiAction, onQuote, saveSource }: {
  markdown: string; onChange: (value: string) => void; onReference: (note: Note) => void;
  workspaceId: string; noteId: string; title?: React.ReactNode; toolbarTarget?: HTMLElement | null; editable?: boolean;
  /** 选区 / 光标在正文 Markdown 里是哪一段(见 noteSelection)。笔记页把它交给助手当上下文。 */
  onSelectionChange?: (selection: NoteSelection | null) => void;
  /** 选区工具条上的「问 AI」:带着这段打开助手、光标进输入框。不给就没有这颗。 */
  onAskAi?: (selection: NoteSelection) => void;
  /** 选区工具条上的 AI 快捷动作(润色、翻译……):交给笔记页去投递给助手。 */
  onAiAction?: (action: NoteAiAction, selection: NoteSelection) => void;
  /** 选区工具条上的「引用到对话」:只把这段挂进助手输入框,不发。 */
  onQuote?: (selection: NoteSelection) => void;
  /** 「存到笔记」时给新笔记记的来源(就是这一篇)。 */
  saveSource?: NoteSource;
}) {
  const s = useNoteStrings();
  const { locale } = usePreferences();
  const change = React.useRef(onChange); change.current = onChange;
  const selectionChange = React.useRef(onSelectionChange); selectionChange.current = onSelectionChange;
  //: 选区工具条先拿按键(Tab 进工具条、Esc 收起),见 NoteSelectionToolbar。编辑器的 props 建好就不再换,所以走 ref。
  const toolbarKeys = React.useRef<ToolbarKeys | null>(null);
  const readAloud = useReadAloud(workspaceId, s.selection);
  //: 「存到笔记」用现有的保存对话框:它的开关在它自己手里,这里只接住它交出来的 open。头一次要存时才挂上它
  //: (它要查笔记列表),之后每要一次(n 变了)就打开一次。
  const [saving, setSaving] = React.useState<{ markdown: string; n: number } | null>(null);
  const openSave = React.useRef<() => void>(() => {});
  React.useEffect(() => { if (saving) openSave.current(); }, [saving]);
  //: 「加到画板」:要放上去的那段纯文字;有就开着画板选择器。
  const [boarding, setBoarding] = React.useState<string | null>(null);
  const reference = React.useRef(onReference); reference.current = onReference;
  const [stuck, setStuck] = React.useState(false);
  const sentinel = React.useRef<HTMLDivElement>(null);
  const [uploading, setUploading] = React.useState(false);
  const fileInput = React.useRef<HTMLInputElement>(null);
  const menu = useSuggestionMenu<Note>({ emptyHint: () => s.noResults });
  const upload = React.useRef<(files: File[], at?: number) => void>(() => {});
  const markdownPaste = React.useRef<(text: string) => void>(() => {});
  const editor = useEditor({
    extensions: [...noteExtensions(!editable, locale), InactiveSelection, Placeholder.configure({ placeholder: notePlaceholder(s.placeholder) }), RefSuggestion.configure({ suggestion: {
      char: "@", allowedPrefixes: null,
      items: async ({ query }) => { try { return (await listNotes(workspaceId, query)).filter(n => n.id !== noteId).slice(0, 12); } catch { return []; } },
      command: ({ editor: instance, range, props }) => {
        const note = props as Note;
        reference.current(note);
        instance.chain().focus().deleteRange(range).insertContent([{ type: "noteReference", attrs: { href: noteHref(note.id, note.revision), label: note.title || s.untitled } }, {type: "text", text: " "}]).run();
      }, render: menu.render,
    } })],
    content: markdown, contentType: "markdown", editable,
    editorProps: { attributes: { class: "note-prose outline-none", "aria-label": s.content },
      handleKeyDown: (_view, event) => toolbarKeys.current?.(event) ?? false,
      handlePaste: (view, event) => {
        const files = Array.from(event.clipboardData?.files || []).filter(f => f.type.startsWith("image/"));
        if (files.length) { event.preventDefault(); upload.current(files); return true; }
        // 这篇文档本来就是 Markdown 存的(有 Markdown 视图、保存的也是 Markdown),所以粘进来的
        // 纯文本也按 Markdown 读 —— 此前 `![](地址)` 粘进来是一串字面文字,再被自动链接把地址
        // 包成链接,存下来就成了 `!\[\]([地址](地址))`。带 HTML 的粘贴不动(那条路已经对了),
        // 代码块里也不动(那里粘什么就是什么)。
        const text = event.clipboardData?.getData("text/plain") || "";
        if (!text.trim() || event.clipboardData?.getData("text/html")) return false;
        if (view.state.selection.$from.parent.type.spec.code) return false;
        event.preventDefault();
        markdownPaste.current(text);
        return true;
      },
      handleDrop: (view, event, _slice, moved) => {
        const files = Array.from(event.dataTransfer?.files || []).filter(f => f.type.startsWith("image/"));
        if (moved || !files.length) return false;
        event.preventDefault(); upload.current(files, view.posAtCoords({left: event.clientX, top: event.clientY})?.pos); return true;
      },
    },
    //: **只有改了文档的那个事务才算改动。** 编辑器会自己补结构:文末是表格时补一个空段落好让光标落得下去
    //: (TrailingNode),它挂在随便哪个事务后面(代码高亮挂装饰的那一下、聚焦就够)。那一下文档变了、update 照发,
    //: 可它不是谁写的字 —— 当成改动的话,只是打开一篇就按编辑器的排版(表格补齐空格、空行数)重写、自动保存,
    //: 多出一版看不出改动的「手动编辑」。补上的结构和排版跟着下一次真改动一起存。
    onUpdate: ({ editor: e, transaction }) => { if (transaction.docChanged) change.current(e.getMarkdown()); },
  });
  React.useEffect(() => {
    const element = sentinel.current;
    if (!element) return;
    const observer = new IntersectionObserver(([entry]) => setStuck(!entry.isIntersecting), { root: element.closest(".note-body") });
    observer.observe(element);
    return () => observer.disconnect();
  }, [editable, editor]);
  // Compare against the last emitted value: parent autosave must not rebuild the document or move the caret.
  // **换了一篇**才整份换掉、光标放回开头。不放的话它按旧文档的位置映射到新文档**末尾** —— 新笔记以列表
  // 结尾时,一打开「无序列表」就亮着,而你根本没点进去。
  // **同一篇**从外面来了新的一版(智能体改了一段、恢复版本、载入最新版本):按最小差异接(followMarkdown)——
  // 只动改了的那一段、光标照常映射,而且进撤销历史:智能体改的那一段,Ctrl+Z 就退回去。
  //: 组词期间不回灌:组词中的字还没进文档,getMarkdown() 和 markdown 必然对不上(见 useExternalContent)。
  const syncedNote = React.useRef(noteId);
  useExternalContent(editor, (instance) => {
    const sameNote = syncedNote.current === noteId;
    syncedNote.current = noteId;
    if (instance.getMarkdown() === markdown) return;
    if (sameNote) { followMarkdown(instance, markdown); return; }
    instance.chain().setContent(markdown, { contentType: "markdown", emitUpdate: false })
      .command(({ tr }) => { tr.setSelection(Selection.atStart(tr.doc)); return true; }).run();
  }, [markdown, noteId]);
  React.useEffect(() => {
    if (!editor) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const report = () => {
      if (!selectionChange.current) return;
      clearTimeout(timer);
      timer = setTimeout(() => { if (!editor.isDestroyed) selectionChange.current?.(readNoteSelection(editor)); }, SELECTION_REPORT_MS);
    };
    editor.on("selectionUpdate", report); editor.on("update", report);
    return () => { clearTimeout(timer); editor.off("selectionUpdate", report); editor.off("update", report); };
  }, [editor]);
  React.useEffect(() => { editor?.setEditable(editable, false); }, [editor, editable]);
  //: 对话气泡里那行选区摘录点进来:把那一段选中、滚到眼前。不是这篇、或编辑器还没好,就留在信箱里等(见 lib/deepLink)。
  useOpenRequest(NOTE_PASSAGE_EVENT, (raw) => {
    const passage = parseNotePassage(raw);
    if (!passage) return;
    if (!editor || editor.isDestroyed || passage.noteId !== noteId) return false;
    const range = findPassage(editor, passage.text, passage.start);
    if (!range) { toast.message(s.passageGone); return; }
    editor.chain().focus().setTextSelection(range).run();
    try { editor.commands.scrollIntoView(); } catch { /* 没有版面信息(测试环境)时滚不了,选中照样成立。 */ }
  }, [editor, noteId]);
  markdownPaste.current = (text) => { editor?.chain().focus().insertContent(text, { contentType: "markdown" }).run(); };
  upload.current = async (files, at) => {
    if (!editor || !editable || uploading) return;
    setUploading(true);
    // A bookmark maps through edits made while uploading, preserving the insertion location.
    let bookmark = editor.state.selection.getBookmark();
    if (at != null) { editor.commands.setTextSelection(at); bookmark = editor.state.selection.getBookmark(); }
    const map = ({ transaction }: { transaction: import("@tiptap/pm/state").Transaction }) => { bookmark = bookmark.map(transaction.mapping); };
    editor.on("transaction", map);
    try {
      for (const file of files) {
        const asset = await importAsset({ workspaceId, file });
        if (editor.isDestroyed) return;
        const selection = bookmark.resolve(editor.state.doc);
        editor.chain().focus().setTextSelection(selection.from).setImage({ src: `mosael-asset:${asset.id}`, alt: file.name }).run();
      }
    } catch (e) { toast.error(errorText(e)); }
    finally { editor.off("transaction", map); setUploading(false); }
  };
  if (!editor) return null;
  const toolbar = <NoteFormatToolbar editor={editor} uploading={uploading} onPickImage={() => fileInput.current?.click()} stuck={toolbarTarget ? undefined : stuck} />;
  return <>{editable && (toolbarTarget ? createPortal(toolbar, toolbarTarget) : <><div ref={sentinel} className="note-format-sentinel" aria-hidden="true" />{toolbar}</>)}{title}<EditorContent editor={editor} />
  {editable && <input type="file" hidden multiple ref={fileInput} accept="image/*" onChange={e => { upload.current(Array.from(e.target.files || [])); e.target.value = ""; }} />}
  {editable && <NoteSelectionToolbar editor={editor} keys={toolbarKeys} readAloud={readAloud} onAskAi={onAskAi} onAiAction={onAiAction} onQuote={onQuote}
    onSaveToNote={markdown => setSaving(previous => ({ markdown, n: (previous?.n ?? 0) + 1 }))} onAddToBoard={setBoarding} />}
  {boarding !== null && <AddToBoardDialog workspaceId={workspaceId} text={boarding} source={saveSource} onClose={() => setBoarding(null)} />}
  {saving && <SaveToNote workspaceId={workspaceId} content={saving.markdown} sources={saveSource ? [{ ...saveSource, quote: saving.markdown.slice(0, 280) }] : []}
    trigger={({ open }) => { openSave.current = open; return null; }} />}
  <menu.Portal className="fixed z-[80] w-[340px] max-w-[calc(100vw-24px)] rounded-xl p-1.5" header={<div className="px-3 py-2 text-xs text-muted-foreground">{s.addReference}</div>}>
    {(note, index) => <button type="button" key={note.id} role="option" aria-selected={menu.menu?.active === index} className={`note-list-row ${menu.menu?.active === index ? "bg-secondary" : ""}`} onMouseDown={e => e.preventDefault()} onClick={() => menu.choose(note)}><strong>{note.title || s.untitled}</strong><p>{note.markdown.slice(0,100)}</p></button>}
  </menu.Portal></>;
}
