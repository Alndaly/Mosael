import React from "react";
import Placeholder from "@tiptap/extension-placeholder";
import { Markdown } from "@tiptap/markdown";
import { EditorContent, useEditor, useEditorState } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import {
  Bold,
  Code,
  Heading1,
  Heading2,
  Heading3,
  Italic,
  List,
  ListOrdered,
  Minus,
  Quote,
  Redo2,
  SquareCode,
  Strikethrough,
  Undo2,
} from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/**
 * 知识库正文编辑器:tiptap(Revornix 同款技术栈的精简版)。
 * 存储仍是 markdown —— Markdown 扩展负责双向转换,检索/智能体
 * 读到的内容不变,只有编辑体验从裸 textarea 升级为所见即所得。
 */
export function KbTiptap({
  initialMarkdown,
  onChange,
}: {
  initialMarkdown: string;
  onChange: (markdown: string) => void;
}) {
  const t = useI18n();
  const editor = useEditor({
    extensions: [
      StarterKit,
      Markdown,
      Placeholder.configure({ placeholder: t("kbContentPlaceholder") }),
    ],
    content: initialMarkdown,
    contentType: "markdown",
    onUpdate: ({ editor: instance }) => onChange(instance.getMarkdown()),
  });

  const active = useEditorState({
    editor,
    selector: ({ editor: instance }) => ({
      bold: instance?.isActive("bold") ?? false,
      italic: instance?.isActive("italic") ?? false,
      strike: instance?.isActive("strike") ?? false,
      code: instance?.isActive("code") ?? false,
      h1: instance?.isActive("heading", { level: 1 }) ?? false,
      h2: instance?.isActive("heading", { level: 2 }) ?? false,
      h3: instance?.isActive("heading", { level: 3 }) ?? false,
      bulletList: instance?.isActive("bulletList") ?? false,
      orderedList: instance?.isActive("orderedList") ?? false,
      blockquote: instance?.isActive("blockquote") ?? false,
      codeBlock: instance?.isActive("codeBlock") ?? false,
      canUndo: instance?.can().undo() ?? false,
      canRedo: instance?.can().redo() ?? false,
    }),
  });

  if (!editor) return null;
  const chain = () => editor.chain().focus();

  const buttons: Array<
    { key: string; icon: React.ReactNode; label: string; active?: boolean; disabled?: boolean; run: () => void } | "sep"
  > = [
    { key: "bold", icon: <Bold size={13} />, label: "加粗", active: active?.bold, run: () => chain().toggleBold().run() },
    { key: "italic", icon: <Italic size={13} />, label: "斜体", active: active?.italic, run: () => chain().toggleItalic().run() },
    { key: "strike", icon: <Strikethrough size={13} />, label: "删除线", active: active?.strike, run: () => chain().toggleStrike().run() },
    { key: "code", icon: <Code size={13} />, label: "行内代码", active: active?.code, run: () => chain().toggleCode().run() },
    "sep",
    { key: "h1", icon: <Heading1 size={13} />, label: "标题 1", active: active?.h1, run: () => chain().toggleHeading({ level: 1 }).run() },
    { key: "h2", icon: <Heading2 size={13} />, label: "标题 2", active: active?.h2, run: () => chain().toggleHeading({ level: 2 }).run() },
    { key: "h3", icon: <Heading3 size={13} />, label: "标题 3", active: active?.h3, run: () => chain().toggleHeading({ level: 3 }).run() },
    "sep",
    { key: "ul", icon: <List size={13} />, label: "无序列表", active: active?.bulletList, run: () => chain().toggleBulletList().run() },
    { key: "ol", icon: <ListOrdered size={13} />, label: "有序列表", active: active?.orderedList, run: () => chain().toggleOrderedList().run() },
    { key: "quote", icon: <Quote size={13} />, label: "引用", active: active?.blockquote, run: () => chain().toggleBlockquote().run() },
    { key: "codeblock", icon: <SquareCode size={13} />, label: "代码块", active: active?.codeBlock, run: () => chain().toggleCodeBlock().run() },
    { key: "hr", icon: <Minus size={13} />, label: "分割线", run: () => chain().setHorizontalRule().run() },
    "sep",
    { key: "undo", icon: <Undo2 size={13} />, label: "撤销", disabled: !active?.canUndo, run: () => chain().undo().run() },
    { key: "redo", icon: <Redo2 size={13} />, label: "重做", disabled: !active?.canRedo, run: () => chain().redo().run() },
  ];

  return (
    <div className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden rounded-lg border border-border bg-panel">
      <div className="flex flex-wrap items-center gap-0.5 border-b border-border px-1.5 py-[5px]" role="toolbar">
        {buttons.map((item, index) =>
          item === "sep" ? (
            <span className="mx-1 h-4 w-px bg-border" key={`sep-${index}`} />
          ) : (
            <Tooltip key={item.key}>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className={cn(
                    "grid h-[26px] w-[26px] cursor-pointer place-items-center rounded-md border-0 bg-transparent text-muted-foreground transition-colors duration-100 hover:bg-secondary hover:text-foreground disabled:cursor-default disabled:opacity-40",
                    item.active && "bg-accent text-accent-foreground hover:bg-accent hover:text-accent-foreground",
                  )}
                  disabled={item.disabled}
                  aria-label={item.label}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={item.run}
                >
                  {item.icon}
                </button>
              </TooltipTrigger>
              <TooltipContent>{item.label}</TooltipContent>
            </Tooltip>
          ),
        )}
      </div>
      <EditorContent editor={editor} className="min-h-0 overflow-y-auto [&_.ProseMirror]:min-h-full [&_.ProseMirror]:px-4 [&_.ProseMirror]:pb-10 [&_.ProseMirror]:pt-3 [&_.ProseMirror]:text-[13.5px] [&_.ProseMirror]:leading-[1.75] [&_.ProseMirror]:text-foreground [&_.ProseMirror]:outline-none [&_.ProseMirror>*+*]:mt-[0.6em] [&_.ProseMirror_:is(h1,h2,h3)]:mt-[1.1em] [&_.ProseMirror_:is(h1,h2,h3)]:font-bold [&_.ProseMirror_:is(h1,h2,h3)]:leading-[1.35] [&_.ProseMirror_h1]:text-xl [&_.ProseMirror_h2]:text-[16.5px] [&_.ProseMirror_h3]:text-[14.5px] [&_.ProseMirror_:is(ul,ol)]:pl-[22px] [&_.ProseMirror_blockquote]:ml-0 [&_.ProseMirror_blockquote]:border-l-2 [&_.ProseMirror_blockquote]:border-border-strong [&_.ProseMirror_blockquote]:pl-3 [&_.ProseMirror_blockquote]:text-muted-foreground [&_.ProseMirror_code]:rounded-sm [&_.ProseMirror_code]:bg-secondary [&_.ProseMirror_code]:px-[5px] [&_.ProseMirror_code]:py-px [&_.ProseMirror_code]:text-xs [&_.ProseMirror_pre]:overflow-x-auto [&_.ProseMirror_pre]:rounded-md [&_.ProseMirror_pre]:border [&_.ProseMirror_pre]:border-border [&_.ProseMirror_pre]:bg-secondary [&_.ProseMirror_pre]:px-2.5 [&_.ProseMirror_pre]:py-2 [&_.ProseMirror_pre_code]:bg-transparent [&_.ProseMirror_pre_code]:p-0 [&_.ProseMirror_hr]:my-3.5 [&_.ProseMirror_hr]:border-0 [&_.ProseMirror_hr]:border-t [&_.ProseMirror_hr]:border-border [&_.ProseMirror_p.is-editor-empty:first-child::before]:pointer-events-none [&_.ProseMirror_p.is-editor-empty:first-child::before]:float-left [&_.ProseMirror_p.is-editor-empty:first-child::before]:h-0 [&_.ProseMirror_p.is-editor-empty:first-child::before]:text-muted-foreground [&_.ProseMirror_p.is-editor-empty:first-child::before]:content-[attr(data-placeholder)]" />
    </div>
  );
}
