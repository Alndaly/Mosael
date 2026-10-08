import React from "react";
import { useEditorState, type Editor } from "@tiptap/react";
import {
  AtSign, Bold, ChevronDown, Code2, Highlighter, ImagePlus, Italic, Link, List, ListOrdered, ListTodo, Minus,
  MoreVertical, Plus, Quote, Redo2, Strikethrough, Table2, Undo2, type LucideIcon,
} from "lucide-react";

import { IconButton } from "@/components/ui/icon-button";
import { MenuContent, MenuItem, MenuSeparator } from "@/components/ui/menu";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Hint } from "@/components/ui/tooltip";
import { formatCombo } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";
import { HIGHLIGHT } from "./NoteHighlight";
import { useNoteStrings } from "./strings";
import { TableSizePicker, type TableSize } from "./TableSizePicker";

/**
 * 笔记的格式工具栏(顶栏左边那一排):段落类型 | 粗体 斜体 删除线 高亮 | 三种列表 | 插入▾ 链接 表格 | 撤销 重做。
 *
 * **窄了按优先级收组,不换行、不重叠。** 放不下时先收「插入 / 链接 / 表格」,再收撤销重做(有快捷键),再收列表,
 * 最后收粗体那一组;段落类型一直在。收起来的组进最右边的「更多格式」,菜单里点了和按钮一样作用在正文上。
 * 每组多宽:显示着的时候量下来记住;收起来的组不在页面上量不到,就用上次量的;还没量过(没有版面的测试环境)
 * 按版面的刻度估(按钮 30px、组内 2px、组间 6px + 一条线 + 6px)。头一次渲染是全部组都在的,所以一挂上就都量过了。
 * 「更多格式」用竖的 ⋮,和右边「笔记操作」那颗横的 ⋯ 分得开。
 *
 * **表格**:光标不在表格里时,那颗按钮叫「插入表格」,点开是一张格子(TableSizePicker),移到几行几列点下去就插入多大的;
 * 在表格里时叫「表格」,点开是加行、加列、删行、删列、删表格。收进「更多格式」时同样:「插入表格」就地展开那张格子。
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

type Action = {
  name: string; icon: LucideIcon; active?: boolean; disabled?: boolean; run: () => void;
  /** 名字下面一行淡色的补充(菜单里显示)。 */
  description?: string;
  /** 快捷键(编辑器里真的绑着的那个,规范串见 lib/shortcuts)。 */
  shortcut?: string;
  /** 点不了的原因(悬停说明里显示)。 */
  disabledReason?: string;
};

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
  const [moreTable, setMoreTable] = React.useState(false);
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
    { name: s.bold, icon: Bold, active: state.bold, shortcut: "Mod+B", run: () => chain().toggleBold().run() },
    { name: s.italic, icon: Italic, active: state.italic, shortcut: "Mod+I", run: () => chain().toggleItalic().run() },
    { name: s.strike, icon: Strikethrough, active: state.strike, shortcut: "Mod+Shift+S", run: () => chain().toggleStrike().run() },
    { name: s.selection.highlight, icon: Highlighter, active: state.highlight, shortcut: "Mod+Shift+H", run: () => chain().toggleMark(HIGHLIGHT).run() },
  ];
  const lists: Action[] = [
    { name: s.bulletList, icon: List, active: state.bullet, shortcut: "Mod+Shift+8", run: () => chain().toggleBulletList().run() },
    { name: s.numberedList, icon: ListOrdered, active: state.ordered, shortcut: "Mod+Shift+7", run: () => chain().toggleOrderedList().run() },
    { name: s.taskList, icon: ListTodo, active: state.task, shortcut: "Mod+Shift+9", run: () => chain().toggleTaskList().run() },
  ];
  const inserts: Action[] = [
    { name: s.quote, icon: Quote, active: state.quote, run: () => chain().toggleBlockquote().run() },
    { name: s.code, icon: Code2, active: state.code, run: () => chain().toggleCodeBlock().run() },
    { name: s.divider, icon: Minus, run: () => chain().setHorizontalRule().run() },
    { name: s.addReference, icon: AtSign, run: () => chain().insertContent("@").run() },
    { name: uploading ? s.uploading : s.image, description: uploading ? undefined : s.imageHint, icon: ImagePlus, disabled: uploading, run: onPickImage },
  ];
  const tableEdits: [string, () => void][] = [
    [s.addRow, () => chain().addRowAfter().run()], [s.addColumn, () => chain().addColumnAfter().run()],
    [s.deleteRow, () => chain().deleteRow().run()], [s.deleteColumn, () => chain().deleteColumn().run()], [s.deleteTable, () => chain().deleteTable().run()],
  ];
  //: 插进去之后焦点归正文(光标在表格第一格):浮层收起时别把焦点先还给按钮 —— 编辑器要等下一帧才拿回焦点,
  //: 这中间按钮上的悬停说明会闪一下(方向键选的,说明认键盘聚焦)。Esc 收起的那种照旧回到按钮。
  const inserted = React.useRef(false);
  const insertTable = ({ rows, cols }: TableSize) => {
    inserted.current = true;
    setOpen(null);
    setMoreTable(false);
    chain().insertTable({ rows, cols, withHeaderRow: true }).run();
  };
  const keepEditorFocus = (event: Event) => {
    if (!inserted.current) return;
    inserted.current = false;
    event.preventDefault();
  };
  const history: Action[] = [
    { name: s.undo, icon: Undo2, disabled: !state.undo, disabledReason: s.nothingToUndo, shortcut: "Mod+Z", run: () => chain().undo().run() },
    { name: s.redo, icon: Redo2, disabled: !state.redo, disabledReason: s.nothingToRedo, shortcut: "Mod+Shift+Z", run: () => chain().redo().run() },
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
    <IconButton unstyled key={action.name} label={action.name} shortcut={action.shortcut && formatCombo(action.shortcut)}
      aria-pressed={action.active} disabled={action.disabled} disabledReason={action.disabledReason}
      onMouseDown={(event) => event.preventDefault()} onClick={action.run}>
      <action.icon size={16} strokeWidth={1.7} />
    </IconButton>
  );
  const item = (key: string, label: string, Icon: LucideIcon | null, run: () => void, extra: Partial<Action> = {}) => (
    <MenuItem key={key} icon={Icon ? <Icon size={16} /> : undefined} inset={!Icon} label={label} description={extra.description}
      shortcut={extra.shortcut && formatCombo(extra.shortcut)} checked={extra.active} aria-pressed={extra.active} disabled={extra.disabled}
      onClick={() => { setOpen(null); run(); }} />
  );
  const actionItems = (actions: Action[]) => actions.map((one) => item(one.name, one.name, one.icon, one.run, one));

  const groups: Record<GroupId, React.ReactNode> = {
    block: (
      //: 段落样式和「插入」是同一种控件:文字 + 小箭头的菜单按钮,菜单条目和右键菜单一个样。
      <Popover open={open === "block"} onOpenChange={(next) => setOpen(next ? "block" : null)}>
        {/* 按钮上显示的是当前段落样式(「正文」「二级标题」),它管什么得悬停说一声。 */}
        <Hint label={s.heading}>
          <PopoverTrigger asChild><button type="button" className="note-format-menu note-block-style" aria-label={s.heading} onMouseDown={(event) => event.preventDefault()}><span>{state.heading ? s.headingLevels[state.heading - 1] : s.paragraph}</span><ChevronDown size={12} /></button></PopoverTrigger>
        </Hint>
        <MenuContent align="start" label={s.heading} onCloseAutoFocus={(event) => event.preventDefault()}>
          {[0, 1, 2, 3, 4, 5, 6].map((level) => (
            <MenuItem key={level} role="menuitemradio" checked={state.heading === level}
              label={level ? <span className="note-heading-option"><span>H{level}</span>{s.headingLevels[level - 1]}</span> : s.paragraph}
              shortcut={formatCombo(`Mod+Alt+${level}`)}
              onClick={() => {
                setOpen(null);
                if (level === 0) chain().setParagraph().run();
                else chain().setHeading({ level: level as 1 | 2 | 3 | 4 | 5 | 6 }).run();
              }} />
          ))}
        </MenuContent>
      </Popover>
    ),
    marks: marks.map(button),
    lists: lists.map(button),
    insert: (
      <>
        <Popover open={open === "insert"} onOpenChange={(next) => setOpen(next ? "insert" : null)}>
          <PopoverTrigger asChild><button type="button" className="note-format-menu note-format-insert" aria-label={s.insert}><Plus size={16} strokeWidth={1.7} /><span>{s.insert}</span><ChevronDown size={12} /></button></PopoverTrigger>
          <MenuContent label={s.insert} align="start">{actionItems(inserts)}</MenuContent>
        </Popover>
        <Popover open={open === "link"} onOpenChange={(next) => { setOpen(next ? "link" : null); if (next) openLink(); }}>
          <PopoverTrigger asChild><IconButton unstyled label={s.link}><Link size={16} strokeWidth={1.7} /></IconButton></PopoverTrigger>
          <PopoverContent className="w-80 p-3">{linkForm}</PopoverContent>
        </Popover>
        <Popover open={open === "table"} onOpenChange={(next) => setOpen(next ? "table" : null)}>
          <PopoverTrigger asChild><IconButton unstyled label={state.table ? s.table : s.insertTable} aria-pressed={state.table}><Table2 size={16} strokeWidth={1.7} /></IconButton></PopoverTrigger>
          {state.table
            ? <MenuContent label={s.table} align="start">{tableEdits.map(([label, run]) => item(label, label, null, run))}</MenuContent>
            : <PopoverContent align="start" className="w-auto p-3" onCloseAutoFocus={keepEditorFocus}><TableSizePicker onPick={insertTable} /></PopoverContent>}
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
        <MenuItem aria-expanded={moreLink} icon={<Link size={16} />} label={s.link} onClick={() => { openLink(); setMoreLink(!moreLink); }} />
        {moreLink && <div className="px-2 pb-2">{linkForm}</div>}
        {state.table ? tableEdits.map(([label, run]) => item(label, label, Table2, run)) : (
          <>
            <MenuItem aria-expanded={moreTable} icon={<Table2 size={16} />} label={s.insertTable} onClick={() => setMoreTable(!moreTable)} />
            {moreTable && <div className="px-2 pb-2"><TableSizePicker autoFocus onPick={insertTable} /></div>}
          </>
        )}
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
          <Popover open={open === "more"} onOpenChange={(next) => { setOpen(next ? "more" : null); if (!next) { setMoreLink(false); setMoreTable(false); } }}>
            <PopoverTrigger asChild><IconButton unstyled label={s.moreFormats}><MoreVertical size={16} strokeWidth={1.7} /></IconButton></PopoverTrigger>
            <MenuContent label={s.moreFormats} align="end" onCloseAutoFocus={keepEditorFocus}>
              {collapsed.map((id, index) => (
                <React.Fragment key={id}>
                  {index > 0 && <MenuSeparator />}
                  {moreItems[id]()}
                </React.Fragment>
              ))}
            </MenuContent>
          </Popover>
        </div>
      )}
    </div>
  );
}
