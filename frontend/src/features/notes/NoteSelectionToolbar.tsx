import React from "react";
import { createPortal } from "react-dom";
import { useEditorState, type Editor } from "@tiptap/react";
import {
  BookPlus, Bold, Bot, ChevronDown, Code, Copy, Highlighter, Italic, LayoutGrid, Link, List, ListTodo, MoreHorizontal, Sparkles, Square,
  Strikethrough, TextQuote, Unlink, Volume2, type LucideIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { FLOATING_SURFACE, MENU_ITEM } from "@/components/ui/floating";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { isImeKeystroke } from "@/lib/shortcuts";
import { readNoteSelection, type NoteSelection } from "./noteSelection";
import { HIGHLIGHT } from "./NoteHighlight";
import type { ReadAloud } from "./readAloud";
import { useNoteStrings } from "./strings";

/**
 * 选中文字后浮在选区旁边的工具条:格式、AI 快捷动作、问 AI、复制、转列表 / 待办、引用到对话、朗读、存到笔记。
 *
 * - **出现**:编辑器有焦点、选区非空;焦点进了工具条自己(键盘 Tab 进来、开着下拉、在填链接)也留着。
 * - **位置**:选区上方;贴着窗口顶部(顶栏底下)放不下就翻到选区下方;左右收进窗口。上下都错开选区的那几行,
 *   不盖住选中的字。选区变了、页面滚了、窗口变了都重新摆。
 * - **键盘**:编辑器里 Tab 进工具条(这时 Tab 不再缩进列表 —— 选中了一段字时进工具条更常用),方向键 / Home / End
 *   在按钮间走,Esc 收起并回到正文(在正文里按 Esc 也收起)。选区一变,收起作废、重新出现。
 * - **窄屏**:只留「问 AI」和「更多」,其余都进「更多」菜单。
 *
 * 高亮存成 `==文字==`(见 NoteHighlight),快捷键 Mod+Shift+H,已高亮的再点一次取消。
 */

export const NOTE_AI_ACTIONS = ["polish", "rewrite", "expand", "shorten", "translate", "summarize", "explain", "continue"] as const;
export type NoteAiAction = (typeof NOTE_AI_ACTIONS)[number];

/** 编辑器把按键先交给工具条:返回 true 表示这一下归工具条(编辑器不再处理)。 */
export type ToolbarKeys = (event: KeyboardEvent) => boolean;

/** 离选区多远、最高能浮到哪(窗口顶栏之下)、离窗口左右边至少多远;量不出自身高度时按这个算。 */
const GAP = 8;
const MIN_TOP = 64;
const EDGE = 8;
const FALLBACK_HEIGHT = 36;
/** 比它窄就收成「问 AI」+「更多」。 */
const NARROW = 640;

type Item = { id: string; label: string; icon: LucideIcon; pressed?: boolean; run: () => void };

export function NoteSelectionToolbar({ editor, keys, readAloud, onAskAi, onAiAction, onQuote, onSaveToNote, onAddToBoard }: {
  editor: Editor;
  keys: React.MutableRefObject<ToolbarKeys | null>;
  readAloud: ReadAloud;
  onAskAi?: (selection: NoteSelection) => void;
  onAiAction?: (action: NoteAiAction, selection: NoteSelection) => void;
  onQuote?: (selection: NoteSelection) => void;
  onSaveToNote?: (markdown: string) => void;
  /** 「加到画板」:交出选区的纯文字(画板上的便签按纯文字显示),由编辑器打开画板选择器。 */
  onAddToBoard?: (text: string) => void;
}) {
  const s = useNoteStrings();
  const ss = s.selection;
  const state = useEditorState({ editor, selector: ({ editor: e }) => ({
    empty: e.state.selection.empty, from: e.state.selection.from, to: e.state.selection.to, focused: e.isFocused,
    bold: e.isActive("bold"), italic: e.isActive("italic"), strike: e.isActive("strike"), code: e.isActive("code"),
    highlight: e.isActive(HIGHLIGHT),
    link: e.isActive("link"), bullet: e.isActive("bulletList"), task: e.isActive("taskList"),
  }) });
  const range = `${state.from}:${state.to}`;
  const [dismissed, setDismissed] = React.useState<string | null>(null);
  const [inside, setInside] = React.useState(false);
  const [menu, setMenu] = React.useState<"ai" | "more" | null>(null);
  const [linking, setLinking] = React.useState(false);
  const [url, setUrl] = React.useState("");
  const narrow = useNarrow();
  const bar = React.useRef<HTMLDivElement | null>(null);
  React.useEffect(() => { setLinking(false); }, [range]);
  //: 收起之后回到正文(点回编辑器)就重新出现 —— 同一段选区再点一次也算「又要用它」。Esc 收起时我们自己把焦点
  //: 还给正文,那一下不算(skipReset)。
  const skipReset = React.useRef(false);
  React.useEffect(() => {
    const reset = () => {
      if (skipReset.current) { skipReset.current = false; return; }
      setDismissed(null);
    };
    //: 在正文里按下鼠标(重新选一段的开头)也算:焦点没离开过正文时,focus 事件不会来。
    const pointer = () => { skipReset.current = false; setDismissed(null); };
    editor.on("focus", reset);
    editor.view.dom.addEventListener("mousedown", pointer);
    return () => { editor.off("focus", reset); editor.view.dom.removeEventListener("mousedown", pointer); };
  }, [editor]);
  const visible = !state.empty && dismissed !== range && (state.focused || inside || menu !== null || linking);

  const buttons = () => [...(bar.current?.querySelectorAll<HTMLButtonElement>("button:not([disabled])") ?? [])];
  const close = React.useCallback(() => {
    setDismissed(range);
    setInside(false);
    setMenu(null);
    setLinking(false);
  }, [range]);
  React.useEffect(() => {
    if (!visible) return;
    keys.current = (event) => {
      if (event.key === "Tab" && !event.shiftKey && !event.altKey && !event.metaKey && !event.ctrlKey) {
        buttons()[0]?.focus();
        return true;
      }
      if (event.key === "Escape") {
        close();
        return true;
      }
      return false;
    };
    return () => { keys.current = null; };
  }, [visible, close, keys]);

  const [, reposition] = React.useReducer((n: number) => n + 1, 0);
  React.useEffect(() => {
    if (!visible) return;
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
    return () => { window.removeEventListener("scroll", reposition, true); window.removeEventListener("resize", reposition); };
  }, [visible]);
  const [size, setSize] = React.useState({ width: 0, height: 0 });
  React.useLayoutEffect(() => {
    const node = bar.current;
    if (node && (node.offsetWidth !== size.width || node.offsetHeight !== size.height)) setSize({ width: node.offsetWidth, height: node.offsetHeight });
  });
  if (!visible) return null;

  let placement: "above" | "below" = "above";
  let top = EDGE;
  let left = EDGE;
  try {
    const start = editor.view.coordsAtPos(state.from);
    const end = editor.view.coordsAtPos(state.to);
    top = start.top - (size.height || FALLBACK_HEIGHT) - GAP;
    if (top < MIN_TOP) {
      placement = "below";
      top = end.bottom + GAP;
    }
    left = Math.max(EDGE, Math.min(window.innerWidth - size.width - EDGE, start.left));
  } catch { /* 没有版面信息(测试环境):落在左上角也点得到。 */ }

  const plain = () => editor.state.doc.textBetween(state.from, state.to, "\n");
  //: 交给助手的那几样(AI 动作、问 AI、引用)做完就收起:人接下来看的是助手面板,工具条还留着只会挡字。
  //: 格式命令不收 —— 常常要连着点好几样。
  const withSelection = (fn?: (selection: NoteSelection) => void) => {
    const selection = readNoteSelection(editor);
    if (!fn || !selection?.text) return;
    fn(selection);
    close();
  };
  const formats: Item[] = [
    { id: "bold", label: s.bold, icon: Bold, pressed: state.bold, run: () => editor.chain().focus().toggleBold().run() },
    { id: "italic", label: s.italic, icon: Italic, pressed: state.italic, run: () => editor.chain().focus().toggleItalic().run() },
    { id: "strike", label: s.strike, icon: Strikethrough, pressed: state.strike, run: () => editor.chain().focus().toggleStrike().run() },
    { id: "code", label: ss.inlineCode, icon: Code, pressed: state.code, run: () => editor.chain().focus().toggleCode().run() },
    { id: "highlight", label: ss.highlight, icon: Highlighter, pressed: state.highlight, run: () => editor.chain().focus().toggleMark(HIGHLIGHT).run() },
    state.link
      ? { id: "unlink", label: ss.unlink, icon: Unlink, run: () => editor.chain().focus().extendMarkRange("link").unsetLink().run() }
      : { id: "link", label: s.link, icon: Link, run: () => { setUrl(""); setLinking(true); } },
  ];
  const common: Item[] = [
    { id: "copy", label: ss.copy, icon: Copy, run: () => { void navigator.clipboard?.writeText(plain()).then(() => toast.success(ss.copied)); } },
    { id: "bullet", label: s.bulletList, icon: List, pressed: state.bullet, run: () => editor.chain().focus().toggleBulletList().run() },
    { id: "task", label: s.taskList, icon: ListTodo, pressed: state.task, run: () => editor.chain().focus().toggleTaskList().run() },
    ...(onQuote ? [{ id: "quote", label: ss.quote, icon: TextQuote, run: () => withSelection(onQuote) }] : []),
    readAloud.reading
      ? { id: "read", label: ss.stopReading, icon: Square, run: readAloud.stop }
      : { id: "read", label: ss.readAloud, icon: Volume2, run: () => readAloud.start(plain()) },
    ...(onSaveToNote ? [{ id: "save", label: s.saveTo, icon: BookPlus, run: () => { onSaveToNote(readNoteSelection(editor)?.text || plain()); close(); } }] : []),
    ...(onAddToBoard ? [{ id: "board", label: ss.addToBoard, icon: LayoutGrid, run: () => { onAddToBoard(plain()); close(); } }] : []),
  ];
  const applyLink = () => {
    if (!/^https?:\/\/\S+$/i.test(url.trim())) return;
    editor.chain().focus().setLink({ href: url.trim() }).run();
    setLinking(false);
  };
  const aiItems = onAiAction ? NOTE_AI_ACTIONS.map((action) => ({ action, ...ss.actions[action] })) : [];

  const iconButton = (item: Item) => (
    <Button
      key={item.id}
      type="button"
      variant="ghost"
      size="icon-xs"
      aria-label={item.label}
      title={item.label}
      aria-pressed={item.pressed}
      className={cn(item.pressed && "bg-accent text-accent-foreground")}
      onMouseDown={(event) => event.preventDefault()}
      onClick={item.run}
    >
      <item.icon />
    </Button>
  );
  const menuItem = (key: string, label: string, Icon: LucideIcon, run: () => void, hint?: string) => (
    <button key={key} type="button" role="menuitem" title={hint ?? label} className={cn(MENU_ITEM, "w-full text-left")} onClick={() => { setMenu(null); run(); }}>
      <Icon />
      <span className="grid min-w-0">
        <span>{label}</span>
        {hint ? <span className="text-ui-2xs text-muted-foreground">{hint}</span> : null}
      </span>
    </button>
  );
  const askButton = onAskAi ? (
    <Button type="button" variant="ghost" size="xs" onMouseDown={(event) => event.preventDefault()} onClick={() => withSelection(onAskAi)}>
      <Bot />{s.askAi}
    </Button>
  ) : null;
  const separator = <span aria-hidden className="mx-0.5 w-px self-stretch bg-divider" />;

  return createPortal(
    <div
      ref={bar}
      role="toolbar"
      aria-label={ss.toolbar}
      aria-orientation="horizontal"
      data-placement={placement}
      className={cn(FLOATING_SURFACE, "fixed z-[70] flex max-w-[calc(100vw-16px)] items-stretch gap-0.5 p-1")}
      style={{ top, left }}
      onFocus={() => setInside(true)}
      onBlur={(event) => { if (!bar.current?.contains(event.relatedTarget as Node | null)) setInside(false); }}
      onKeyDown={(event) => {
        if (isImeKeystroke(event)) return;
        if (event.key === "Escape") {
          event.preventDefault();
          close();
          //: 直接让视图拿焦点(选区原样留着);commands.focus() 要等下一帧,那之前焦点已经掉到 body 上了。
          skipReset.current = true;
          editor.view.focus();
          return;
        }
        if (!(event.target instanceof HTMLButtonElement)) return;
        const all = buttons();
        const at = all.indexOf(event.target);
        const to = event.key === "ArrowRight" ? at + 1 : event.key === "ArrowLeft" ? at - 1 : event.key === "Home" ? 0 : event.key === "End" ? all.length - 1 : null;
        if (to === null) return;
        event.preventDefault();
        all[(to + all.length) % all.length]?.focus();
      }}
    >
      {linking ? (
        <input
          autoFocus
          type="url"
          aria-label={s.link}
          placeholder={ss.linkPlaceholder}
          value={url}
          className="h-7 w-64 min-w-0 rounded-md bg-field px-2 text-ui-xs outline-none"
          onChange={(event) => setUrl(event.target.value)}
          onKeyDown={(event) => {
            if (isImeKeystroke(event)) return;
            if (event.key === "Enter") { event.preventDefault(); applyLink(); }
            if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); setLinking(false); editor.view.focus(); }
          }}
        />
      ) : narrow ? (
        <>
          {askButton}
          <Popover open={menu === "more"} onOpenChange={(open) => setMenu(open ? "more" : null)}>
            <PopoverTrigger asChild>
              <Button type="button" variant="ghost" size="xs" onMouseDown={(event) => event.preventDefault()}><MoreHorizontal />{ss.more}</Button>
            </PopoverTrigger>
            <PopoverContent role="menu" align="start" className="grid max-h-[var(--radix-popover-content-available-height)] w-56 gap-0.5 overflow-y-auto p-1.5">
              {formats.map((item) => menuItem(item.id, item.label, item.icon, item.run))}
              {aiItems.map((item) => menuItem(item.action, item.label, Sparkles, () => withSelection((selection) => onAiAction?.(item.action, selection)), item.hint))}
              {common.map((item) => menuItem(item.id, item.label, item.icon, item.run))}
            </PopoverContent>
          </Popover>
        </>
      ) : (
        <>
          {formats.map(iconButton)}
          {separator}
          {aiItems.length > 0 && (
            <Popover open={menu === "ai"} onOpenChange={(open) => setMenu(open ? "ai" : null)}>
              <PopoverTrigger asChild>
                <Button type="button" variant="ghost" size="xs" onMouseDown={(event) => event.preventDefault()}><Sparkles />{ss.ai}<ChevronDown /></Button>
              </PopoverTrigger>
              <PopoverContent role="menu" align="start" className="grid max-h-[var(--radix-popover-content-available-height)] w-64 gap-0.5 overflow-y-auto p-1.5">
                {aiItems.map((item) => menuItem(item.action, item.label, Sparkles, () => withSelection((selection) => onAiAction?.(item.action, selection)), item.hint))}
              </PopoverContent>
            </Popover>
          )}
          {askButton}
          {separator}
          {common.map(iconButton)}
        </>
      )}
    </div>,
    document.body,
  );
}

function useNarrow(): boolean {
  const [narrow, setNarrow] = React.useState(() => window.innerWidth < NARROW);
  React.useEffect(() => {
    const update = () => setNarrow(window.innerWidth < NARROW);
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  return narrow;
}
