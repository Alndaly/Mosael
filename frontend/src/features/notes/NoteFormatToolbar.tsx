import React from "react";
import { useEditorState, type Editor } from "@tiptap/react";
import {
  AtSign, Bold, Check, ChevronDown, Code2, Highlighter, ImagePlus, Italic, Link, List, ListOrdered, ListTodo, Minus,
  MoreVertical, Plus, Quote, Redo2, Strikethrough, Table2, Undo2, type LucideIcon,
} from "lucide-react";

import { MENU_ITEM, MENU_SEPARATOR } from "@/components/ui/floating";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { HIGHLIGHT } from "./NoteHighlight";
import { useNoteStrings } from "./strings";

/**
 * 笔记的格式工具栏(顶栏左边那一排):段落类型 | 粗体 斜体 删除线 高亮 | 三种列表 | 插入▾ 链接 表格 | 撤销 重做。
 *
 * **窄了按优先级收组,不换行、不重叠。** 放不下时先收「插入 / 链接 / 表格」,再收撤销重做(有快捷键),再收列表,
 * 最后收粗体那一组;段落类型一直在。收起来的组进最右边的「更多格式」,菜单里点了和按钮一样作用在正文上。
 * 每组多宽:显示着的时候量下来记住;收起来的组不在页面上量不到,就用上次量的;还没量过(没有版面的测试环境)
 * 按版面的刻度估(按钮 30px、组内 2px、组间 6px + 一条线 + 6px)。头一次渲染是全部组都在的,所以一挂上就都量过了。
 * 「更多格式」用竖的 ⋮,和右边「笔记操作」那颗横的 ⋯ 分得开。
 */

type GroupId = "block" | "marks" | "lists" | "insert" | "history";
const ORDER: GroupId[] = ["block", "marks", "lists", "insert", "history"];
/** 收的先后:最低频的先收。段落类型不收(它本身就是个菜单)。 */
const COLLAPSE: GroupId[] = ["insert", "history", "lists", "marks"];
const BUTTON = 30;
const GAP = 2;
const SEPARATOR = 13;
/** 带字的菜单按钮(「正文▾」「插入▾」)按最长的那种语言估;段落类型本身就是定宽 96(见 notes.css)。 */
const MENU_BUTTON = 96;
const ESTIMATE: Record<GroupId, number> = {
  block: MENU_BUTTON,
  marks: 4 * BUTTON + 3 * GAP,
  lists: 3 * BUTTON + 2 * GAP,
  insert: MENU_BUTTON + 2 * BUTTON + 2 * GAP,
  history: 2 * BUTTON + GAP,
};
const MORE = SEPARATOR + BUTTON;
export type FormatGroupWidths = Partial<Record<GroupId, number>>;

/** 这么宽放得下哪几组(纯函数,顺序照 ORDER)。measured 是量到的各组宽度,没量到的用估的。 */
export function visibleFormatGroups(width: number, measured: FormatGroupWidths = {}): GroupId[] {
  const visible = new Set(ORDER);
  const total = () => {
    const shown = ORDER.filter((id) => visible.has(id));
    return shown.reduce((sum, id, index) => sum + (measured[id] || ESTIMATE[id]) + (index ? SEPARATOR : 0), 0) + (shown.length < ORDER.length ? MORE : 0);
  };
  for (const id of COLLAPSE) {
    if (total() <= width) break;
    visible.delete(id);
  }
  return ORDER.filter((id) => visible.has(id));
}

type Action = { name: string; icon: LucideIcon; active?: boolean; disabled?: boolean; run: () => void };

export function NoteFormatToolbar({ editor, uploading, onPickImage, stuck }: {
  editor: Editor;
  uploading: boolean;
  onPickImage: () => void;
  /** 不在顶栏、贴在正文上方时:滚过了就浮起来(见 NoteEditor 的哨兵)。 */
  stuck?: boolean;
}) {
  const s = useNoteStrings();
  const state = useEditorState({ editor, selector: ({ editor: e }) => ({
    bold: e.isActive("bold"), italic: e.isActive("italic"), strike: e.isActive("strike"), highlight: e.isActive(HIGHLIGHT),
    heading: e.isActive("heading") ? Number(e.getAttributes("heading").level) : 0,
    bullet: e.isActive("bulletList"), ordered: e.isActive("orderedList"), task: e.isActive("taskList"),
    quote: e.isActive("blockquote"), code: e.isActive("codeBlock"), table: e.isActive("table"),
    undo: e.can().undo(), redo: e.can().redo(),
  }) });
  const [open, setOpen] = React.useState<"block" | "insert" | "link" | "table" | "more" | null>(null);
  const [moreLink, setMoreLink] = React.useState(false);
  const [url, setUrl] = React.useState("");
  const root = React.useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = React.useState(Infinity);
  React.useLayoutEffect(() => {
    const host = root.current?.parentElement;
    if (!host || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => { if (entry.contentRect.width > 0) setWidth(entry.contentRect.width); });
    observer.observe(host);
    return () => observer.disconnect();
  }, []);
  const measured = React.useRef<FormatGroupWidths>({});
  React.useLayoutEffect(() => {
    //: 一组的宽 = 最左那颗按钮的左边到最右那颗的右边(分隔线和它两边的空不算在组里,另算)。
    for (const group of root.current?.querySelectorAll<HTMLElement>("[data-format-group]") ?? []) {
      const first = group.firstElementChild?.getBoundingClientRect();
      const last = group.lastElementChild?.getBoundingClientRect();
      if (first && last && last.right > first.left) measured.current[group.dataset.formatGroup as GroupId] = Math.ceil(last.right - first.left);
    }
  });
  const visible = visibleFormatGroups(width, measured.current);
  const collapsed = ORDER.filter((id) => !visible.includes(id));

  const chain = () => editor.chain().focus();
  const marks: Action[] = [
    { name: s.bold, icon: Bold, active: state.bold, run: () => chain().toggleBold().run() },
    { name: s.italic, icon: Italic, active: state.italic, run: () => chain().toggleItalic().run() },
    { name: s.strike, icon: Strikethrough, active: state.strike, run: () => chain().toggleStrike().run() },
    { name: s.selection.highlight, icon: Highlighter, active: state.highlight, run: () => chain().toggleMark(HIGHLIGHT).run() },
  ];
  const lists: Action[] = [
    { name: s.bulletList, icon: List, active: state.bullet, run: () => chain().toggleBulletList().run() },
    { name: s.numberedList, icon: ListOrdered, active: state.ordered, run: () => chain().toggleOrderedList().run() },
    { name: s.taskList, icon: ListTodo, active: state.task, run: () => chain().toggleTaskList().run() },
  ];
  const inserts: Action[] = [
    { name: s.quote, icon: Quote, active: state.quote, run: () => chain().toggleBlockquote().run() },
    { name: s.code, icon: Code2, active: state.code, run: () => chain().toggleCodeBlock().run() },
    { name: s.divider, icon: Minus, run: () => chain().setHorizontalRule().run() },
    { name: s.addReference, icon: AtSign, run: () => chain().insertContent("@").run() },
    { name: uploading ? s.uploading : s.image, icon: ImagePlus, disabled: uploading, run: onPickImage },
  ];
  const tableActions: [string, () => void][] = state.table
    ? [[s.addRow, () => chain().addRowAfter().run()], [s.addColumn, () => chain().addColumnAfter().run()],
      [s.deleteRow, () => chain().deleteRow().run()], [s.deleteColumn, () => chain().deleteColumn().run()], [s.deleteTable, () => chain().deleteTable().run()]]
    : [[s.insertTable, () => chain().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()]];
  const history: Action[] = [
    { name: s.undo, icon: Undo2, disabled: !state.undo, run: () => chain().undo().run() },
    { name: s.redo, icon: Redo2, disabled: !state.redo, run: () => chain().redo().run() },
  ];
  const applyLink = (event: React.FormEvent) => {
    event.preventDefault();
    if (url && !/^https?:\/\//i.test(url)) return;
    const link = chain().extendMarkRange("link");
    if (!url) link.unsetLink().run();
    else if (editor.state.selection.empty) link.insertContent({ type: "text", text: url, marks: [{ type: "link", attrs: { href: url } }] }).run();
    else link.setLink({ href: url }).run();
    setOpen(null);
    setMoreLink(false);
  };
  const linkForm = (
    <form className="grid gap-3" onSubmit={applyLink}>
      <label className="text-sm">{s.link}<input className="mt-2 w-full rounded-md bg-secondary p-2 text-sm" aria-label={s.link} placeholder="https://" type="url" value={url} onChange={(event) => setUrl(event.target.value)} /></label>
      <button className="rounded-md bg-secondary p-2 text-sm" type="submit">{s.apply}</button>
    </form>
  );
  const openLink = () => setUrl(String(editor.getAttributes("link").href || ""));

  const button = (action: Action) => (
    <button key={action.name} type="button" title={action.name} aria-label={action.name} aria-pressed={action.active} disabled={action.disabled}
      onMouseDown={(event) => event.preventDefault()} onClick={action.run}>
      <action.icon size={16} strokeWidth={1.7} />
    </button>
  );
  const item = (key: string, label: string, Icon: LucideIcon | null, run: () => void, extra: { active?: boolean; disabled?: boolean } = {}) => (
    <button key={key} type="button" role="menuitem" aria-pressed={extra.active} disabled={extra.disabled} className={cn(MENU_ITEM, "w-full text-left")}
      onClick={() => { setOpen(null); run(); }}>
      {Icon ? <Icon size={16} /> : <span className="size-4" aria-hidden />}
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {extra.active && <Check className="ml-auto" />}
    </button>
  );
  const actionItems = (actions: Action[]) => actions.map((one) => item(one.name, one.name, one.icon, one.run, one));

  const groups: Record<GroupId, React.ReactNode> = {
    block: (
      //: 段落样式和「插入」是同一种控件:文字 + 小箭头的菜单按钮,菜单条目和右键菜单一个样。
      <Popover open={open === "block"} onOpenChange={(next) => setOpen(next ? "block" : null)}>
        <PopoverTrigger asChild><button type="button" className="note-format-menu note-block-style" aria-label={s.heading} title={s.heading} onMouseDown={(event) => event.preventDefault()}><span>{state.heading ? s.headingLevels[state.heading - 1] : s.paragraph}</span><ChevronDown size={12} /></button></PopoverTrigger>
        <PopoverContent align="start" className="grid w-44 gap-0.5 p-1.5" onCloseAutoFocus={(event) => event.preventDefault()}>
          {[0, 1, 2, 3, 4, 5, 6].map((level) => {
            const current = state.heading === level;
            return <button key={level} type="button" role="menuitemradio" aria-checked={current} className={cn(MENU_ITEM, "w-full text-left")} onClick={() => {
              setOpen(null);
              if (level === 0) chain().setParagraph().run();
              else chain().setHeading({ level: level as 1 | 2 | 3 | 4 | 5 | 6 }).run();
            }}>
              {level ? <span className="note-heading-option"><span>H{level}</span>{s.headingLevels[level - 1]}</span> : s.paragraph}
              {current && <Check className="ml-auto" />}
            </button>;
          })}
        </PopoverContent>
      </Popover>
    ),
    marks: marks.map(button),
    lists: lists.map(button),
    insert: (
      <>
        <Popover open={open === "insert"} onOpenChange={(next) => setOpen(next ? "insert" : null)}>
          <PopoverTrigger asChild><button type="button" className="note-format-menu note-format-insert" aria-label={s.insert} title={s.insert}><Plus size={16} strokeWidth={1.7} /><span>{s.insert}</span><ChevronDown size={12} /></button></PopoverTrigger>
          <PopoverContent role="menu" aria-label={s.insert} align="start" className="grid w-48 gap-0.5 p-1.5">{actionItems(inserts)}</PopoverContent>
        </Popover>
        <Popover open={open === "link"} onOpenChange={(next) => { setOpen(next ? "link" : null); if (next) openLink(); }}>
          <PopoverTrigger asChild><button type="button" title={s.link} aria-label={s.link}><Link size={16} strokeWidth={1.7} /></button></PopoverTrigger>
          <PopoverContent className="w-80 p-3">{linkForm}</PopoverContent>
        </Popover>
        <Popover open={open === "table"} onOpenChange={(next) => setOpen(next ? "table" : null)}>
          <PopoverTrigger asChild><button type="button" title={s.table} aria-label={s.table} aria-pressed={state.table}><Table2 size={16} strokeWidth={1.7} /></button></PopoverTrigger>
          <PopoverContent role="menu" aria-label={s.table} align="start" className="grid w-48 gap-0.5 p-1.5">{tableActions.map(([label, run]) => item(label, label, null, run))}</PopoverContent>
        </Popover>
      </>
    ),
    history: history.map(button),
  };
  const moreItems: Record<GroupId, () => React.ReactNode> = {
    block: () => null,
    marks: () => actionItems(marks),
    lists: () => actionItems(lists),
    insert: () => (
      <>
        {actionItems(inserts)}
        <button type="button" role="menuitem" aria-expanded={moreLink} className={cn(MENU_ITEM, "w-full text-left")} onClick={() => { openLink(); setMoreLink(!moreLink); }}>
          <Link size={16} /><span className="min-w-0 flex-1 truncate">{s.link}</span>
        </button>
        {moreLink && <div className="px-2 pb-2">{linkForm}</div>}
        {tableActions.map(([label, run]) => item(label, label, Table2, run))}
      </>
    ),
    history: () => actionItems(history),
  };

  return (
    <div ref={root} className="note-format" data-stuck={stuck} role="toolbar" aria-label={s.format}>
      {visible.map((id) => (
        <div key={id} data-format-group={id} className={cn("note-format-group", id === "history" && "note-format-history")}>{groups[id]}</div>
      ))}
      {collapsed.length > 0 && (
        <div className="note-format-group">
          <Popover open={open === "more"} onOpenChange={(next) => { setOpen(next ? "more" : null); if (!next) setMoreLink(false); }}>
            <PopoverTrigger asChild><button type="button" title={s.moreFormats} aria-label={s.moreFormats}><MoreVertical size={16} strokeWidth={1.7} /></button></PopoverTrigger>
            <PopoverContent role="menu" aria-label={s.moreFormats} align="end" className="flex max-h-[var(--radix-popover-content-available-height)] w-64 flex-col gap-0.5 overflow-y-auto p-1.5">
              {collapsed.map((id, index) => (
                <React.Fragment key={id}>
                  {index > 0 && <div className={MENU_SEPARATOR} role="separator" />}
                  {moreItems[id]()}
                </React.Fragment>
              ))}
            </PopoverContent>
          </Popover>
        </div>
      )}
    </div>
  );
}
