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
    <div className="kb-tiptap">
      <div className="kb-tiptap-toolbar" role="toolbar">
        {buttons.map((item, index) =>
          item === "sep" ? (
            <span className="kb-tt-sep" key={`sep-${index}`} />
          ) : (
            <Tooltip key={item.key}>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className={item.active ? "kb-tt-btn active" : "kb-tt-btn"}
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
      <EditorContent editor={editor} className="kb-tiptap-content" />
    </div>
  );
}
