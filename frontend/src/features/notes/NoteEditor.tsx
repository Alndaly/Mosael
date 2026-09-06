import { useEditor, EditorContent, useEditorState } from "@tiptap/react";
import Placeholder from "@tiptap/extension-placeholder";
import React from "react";
import { Bold, Italic, List, ListOrdered, Quote, Heading2, Undo2, Redo2, AtSign, ImagePlus, Table2, ListTodo, Code2, Link, Minus, Strikethrough, Plus, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import { useNoteStrings } from "./strings";
import { noteExtensions } from "./editorExtensions";
import { RefSuggestion } from "@/components/app/refSuggestion";
import { useSuggestionMenu } from "@/components/app/suggestionMenu";
import { listNotes, noteHref, type Note } from "@/api/domains/notes";
import { importAsset } from "@/api/domains/assets";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export function NoteReader({ markdown }: { markdown: string }) {
  const editor = useEditor({ extensions: noteExtensions(true), content: markdown, contentType: "markdown", editable: false,
    editorProps: { attributes: { class: "note-prose" } } });
  React.useEffect(() => { editor?.commands.setContent(markdown, {contentType:"markdown", emitUpdate:false}); }, [editor, markdown]);
  return <EditorContent editor={editor} />;
}

export function NoteEditor({ markdown, onChange, onReference, workspaceId, noteId, title, editable = true }: {
  markdown: string; onChange: (value: string) => void; onReference: (note: Note) => void;
  workspaceId: string; noteId: string; title?: React.ReactNode; editable?: boolean;
}) {
  const s = useNoteStrings();
  const change = React.useRef(onChange); change.current = onChange;
  const reference = React.useRef(onReference); reference.current = onReference;
  const [insertOpen, setInsertOpen] = React.useState(false);
  const [stuck, setStuck] = React.useState(false);
  const sentinel = React.useRef<HTMLDivElement>(null);
  const [uploading, setUploading] = React.useState(false);
  const [linkOpen, setLinkOpen] = React.useState(false); const [url, setUrl] = React.useState("");
  const fileInput = React.useRef<HTMLInputElement>(null);
  const menu = useSuggestionMenu<Note>({ emptyHint: () => s.noResults });
  const upload = React.useRef<(files: File[], at?: number) => void>(() => {});
  const editor = useEditor({
    extensions: [...noteExtensions(!editable), Placeholder.configure({ placeholder: s.placeholder }), RefSuggestion.configure({ suggestion: {
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
      handlePaste: (_view, event) => {
        const files = Array.from(event.clipboardData?.files || []).filter(f => f.type.startsWith("image/"));
        if (!files.length) return false;
        event.preventDefault(); upload.current(files); return true;
      },
      handleDrop: (view, event, _slice, moved) => {
        const files = Array.from(event.dataTransfer?.files || []).filter(f => f.type.startsWith("image/"));
        if (moved || !files.length) return false;
        event.preventDefault(); upload.current(files, view.posAtCoords({left: event.clientX, top: event.clientY})?.pos); return true;
      },
    },
    onUpdate: ({ editor: e }) => change.current(e.getMarkdown()),
  });
  React.useEffect(() => {
    const element = sentinel.current;
    if (!element) return;
    const observer = new IntersectionObserver(([entry]) => setStuck(!entry.isIntersecting), { root: element.closest(".note-body") });
    observer.observe(element);
    return () => observer.disconnect();
  }, [editable, editor]);
  const state = useEditorState({ editor, selector: ({editor: e}) => ({
    bold: e?.isActive("bold"), italic: e?.isActive("italic"), strike: e?.isActive("strike"), heading: e?.isActive("heading"),
    bullet: e?.isActive("bulletList"), ordered: e?.isActive("orderedList"), task: e?.isActive("taskList"),
    quote: e?.isActive("blockquote"), code: e?.isActive("codeBlock"), table: e?.isActive("table"),
    undo: e?.can().undo(), redo: e?.can().redo(),
  }) });
  // Compare against the last emitted value: parent autosave must not rebuild the document or move the caret.
  React.useEffect(() => { if (editor && editor.getMarkdown() !== markdown) editor.commands.setContent(markdown, { contentType: "markdown", emitUpdate: false }); }, [editor, markdown]);
  React.useEffect(() => { editor?.setEditable(editable, false); }, [editor, editable]);
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
    } catch (e) { toast.error(String(e)); }
    finally { editor.off("transaction", map); setUploading(false); }
  };
  if (!editor) return null;
  const actions = [
    { name: s.bold, icon: Bold, active: state?.bold, action: () => editor.chain().focus().toggleBold().run() },
    { name: s.italic, icon: Italic, active: state?.italic, action: () => editor.chain().focus().toggleItalic().run() },
    { name: s.strike, icon: Strikethrough, active: state?.strike, action: () => editor.chain().focus().toggleStrike().run() },
    { name: s.heading, icon: Heading2, active: state?.heading, action: () => editor.chain().focus().toggleHeading({level: 2}).run() },
    { name: s.bulletList, icon: List, active: state?.bullet, action: () => editor.chain().focus().toggleBulletList().run() },
    { name: s.numberedList, icon: ListOrdered, active: state?.ordered, action: () => editor.chain().focus().toggleOrderedList().run() },
    { name: s.taskList, icon: ListTodo, active: state?.task, action: () => editor.chain().focus().toggleTaskList().run() },
    { name: s.quote, icon: Quote, active: state?.quote, action: () => editor.chain().focus().toggleBlockquote().run() },
    { name: s.code, icon: Code2, active: state?.code, action: () => editor.chain().focus().toggleCodeBlock().run() },
    { name: s.divider, icon: Minus, action: () => editor.chain().focus().setHorizontalRule().run() },
    { name: s.addReference, icon: AtSign, action: () => editor.chain().focus().insertContent("@").run() },
    { name: uploading ? s.uploading : s.image, icon: ImagePlus, disabled: uploading, action: () => fileInput.current?.click() },
    { name: s.undo, icon: Undo2, disabled: !state?.undo, action: () => editor.chain().focus().undo().run() },
    { name: s.redo, icon: Redo2, disabled: !state?.redo, action: () => editor.chain().focus().redo().run() },
  ];
  const actionButton = (a: typeof actions[number]) => <button key={a.name} type="button" title={a.name} aria-label={a.name} aria-pressed={a.active} disabled={a.disabled} onMouseDown={e => e.preventDefault()} onClick={a.action}><a.icon size={16} strokeWidth={1.7} /></button>;
  return <>{editable && <><div ref={sentinel} className="note-format-sentinel" aria-hidden="true" /><div className="note-format" data-stuck={stuck} role="toolbar" aria-label={s.write}>
    <div className="note-format-group">{actions.slice(0,4).map(actionButton)}</div>
    <div className="note-format-group">{actions.slice(4,7).map(actionButton)}</div>
    <div className="note-format-group">
    <Popover open={insertOpen} onOpenChange={setInsertOpen}><PopoverTrigger asChild><button className="note-format-insert" aria-label={s.insert} title={s.insert}><Plus size={16} strokeWidth={1.7} /><span>{s.insert}</span><ChevronDown size={12} /></button></PopoverTrigger>
      <PopoverContent align="start" className="grid w-48 gap-1 p-1.5">{actions.slice(7,12).map(a => <button key={a.name} type="button" disabled={a.disabled} aria-pressed={a.active} className="flex items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-ui-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground" onClick={() => { setInsertOpen(false); a.action(); }}><a.icon size={16} /><span>{a.name}</span></button>)}</PopoverContent>
    </Popover>
    <Popover open={linkOpen} onOpenChange={open => { setLinkOpen(open); if (open) setUrl(String(editor.getAttributes("link").href || "")); }}><PopoverTrigger asChild><button title={s.link} aria-label={s.link}><Link size={16} /></button></PopoverTrigger><PopoverContent className="w-80 p-3"><form className="grid gap-3" onSubmit={e => { e.preventDefault(); if (url && !/^https?:\/\//i.test(url)) return; const chain = editor.chain().focus().extendMarkRange("link"); if (!url) chain.unsetLink().run(); else if (editor.state.selection.empty) chain.insertContent({type: "text", text: url, marks: [{type:"link", attrs:{href:url}}]}).run(); else chain.setLink({href:url}).run(); setLinkOpen(false); }}><label className="text-sm">{s.link}<input className="mt-2 w-full rounded-md bg-secondary p-2 text-sm" aria-label={s.link} placeholder="https://" type="url" value={url} onChange={e => setUrl(e.target.value)} /></label><button className="rounded-md bg-secondary p-2 text-sm" type="submit">{s.apply}</button></form></PopoverContent></Popover>
    <Popover><PopoverTrigger asChild><button title={s.table} aria-label={s.table} aria-pressed={state?.table}><Table2 size={16} /></button></PopoverTrigger><PopoverContent className="grid w-48 gap-1 p-2">{(state?.table ? [
      [s.addRow, () => editor.chain().focus().addRowAfter().run()], [s.addColumn, () => editor.chain().focus().addColumnAfter().run()],
      [s.deleteRow, () => editor.chain().focus().deleteRow().run()], [s.deleteColumn, () => editor.chain().focus().deleteColumn().run()], [s.deleteTable, () => editor.chain().focus().deleteTable().run()],
    ] : [[s.insertTable, () => editor.chain().focus().insertTable({rows:3,cols:3,withHeaderRow:true}).run()]]).map(([label, action]) => <button className="rounded-md px-2 py-1.5 text-left text-sm hover:bg-secondary" key={String(label)} onClick={action as () => void}>{String(label)}</button>)}</PopoverContent></Popover>
    </div>
    <div className="note-format-group note-format-history">{actions.slice(12).map(actionButton)}</div>
    <input type="file" hidden multiple ref={fileInput} accept="image/*" onChange={e => { upload.current(Array.from(e.target.files || [])); e.target.value = ""; }} />
  </div></>}{title}<EditorContent editor={editor} />
  <menu.Portal className="fixed z-[80] w-[340px] max-w-[calc(100vw-24px)] rounded-xl p-1.5" header={<div className="px-3 py-2 text-xs text-muted-foreground">{s.addReference}</div>}>
    {(note, index) => <button type="button" key={note.id} role="option" aria-selected={menu.menu?.active === index} className={`note-list-row ${menu.menu?.active === index ? "bg-secondary" : ""}`} onMouseDown={e => e.preventDefault()} onClick={() => menu.choose(note)}><strong>{note.title || s.untitled}</strong><p>{note.markdown.slice(0,100)}</p></button>}
  </menu.Portal></>;
}
