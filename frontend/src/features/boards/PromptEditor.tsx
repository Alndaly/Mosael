import React from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";

import { assetThumbnailUrl, type Asset } from "@/api/client";
import { RefSuggestion } from "@/components/app/refSuggestion";
import { useSuggestionMenu } from "@/components/app/suggestionMenu";
import { cn } from "@/lib/utils";

/**
 * 画板提示词输入框:一段纯文本,`@` 在**表单内部**引用素材。
 *
 * ## 为什么是 TipTap 而不是 textarea + 自己判 `@`
 *
 * 第一版就是 textarea:自己找光标前那段 `@词`、自己接方向键和回车。它能跑,但错在同一个
 * 地方 —— **输入法**。中文选词时按回车会被菜单当成「选中这一条」吃掉,候选词上不了屏;
 * 而 composition 期间的光标位置也不是那么好算的。这正是工作流那边选 TipTap 的理由
 * (见 components/app/refSuggestion 开头那段),没道理在这里重犯一遍。
 *
 * 菜单的「摆在哪、怎么跟着光标走」也和工作流共用一份(useSuggestionMenu):抄两份的话,
 * 翻面、贴边、跟随都要各修一遍。
 *
 * ## 选中的素材**不写进正文**
 *
 * 它挂到上面那排槽位上去。槽位行是「这次生成挂了什么」的唯一去处 —— 正文里再插一个
 * chip,同一份素材就有了两个说法,而用户删掉其中一个时另一个还在。
 */
export function PromptEditor({
  value,
  onChange,
  placeholder,
  candidates,
  onPick,
  onSubmit,
  emptyHint,
}: {
  value: string;
  onChange: (next: string) => void;
  placeholder: string;
  /** `@` 能挑的素材。由调用方按「这个模型收得下什么」筛过。 */
  candidates: (query: string) => Asset[];
  onPick: (asset: Asset) => void;
  /** ⌘/Ctrl+Enter。 */
  onSubmit: () => void;
  /** 一个候选都没有时说的那句话;返回空串就什么都不弹。 */
  emptyHint: () => string;
}) {
  //: 最后一次自己发出去的值。外面改了(上游便签填进来、撤销)才回灌,否则每敲一个字都会被
  //: prop 回流重建文档,光标跳到开头。
  const emitted = React.useRef(value);
  //: 插件的回调在创建时一次性装好,拿不到后续渲染的闭包 —— 用 ref 兜住当前值。
  const candidatesRef = React.useRef(candidates);
  candidatesRef.current = candidates;
  const pickRef = React.useRef(onPick);
  pickRef.current = onPick;
  const submitRef = React.useRef(onSubmit);
  submitRef.current = onSubmit;

  const menu = useSuggestionMenu<Asset>({
    emptyHint,
    sameItems: (a, b) => a.length === b.length && a.every((one, at) => one.id === b[at].id),
  });

  const editor = useEditor({
    extensions: [
      // 这是**一段提示词**,不是文档:标题、列表、加粗之类一概关掉。
      StarterKit.configure({
        heading: false,
        bulletList: false,
        orderedList: false,
        listItem: false,
        blockquote: false,
        codeBlock: false,
        horizontalRule: false,
        bold: false,
        italic: false,
        strike: false,
        code: false,
      }),
      Placeholder.configure({ placeholder }),
      RefSuggestion.configure({
        suggestion: {
          char: "@",
          // 只在行首或分隔符后唤起 —— 否则邮箱 a@b、句中的 @ 也会弹菜单。
          allowedPrefixes: [" ", "(", "[", "{", ",", ":", "，", "、"],
          items: ({ query }) => candidatesRef.current(query),
          command: ({ editor: instance, range, props }) => {
            //: 把那段 `@词` 从正文里删掉 —— 留着的话模型会把「@猫.png」当成描述念出来。
            instance.chain().focus().deleteRange(range).run();
            pickRef.current(props as unknown as Asset);
          },
          render: menu.render,
        },
      }),
    ],
    content: value ? { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: value }] }] } : undefined,
    editorProps: {
      attributes: {
        // nodrag / nowheel:这东西活在画布上,不挂的话在里面选文字会变成拖画布。
        class:
          "nodrag nowheel min-h-[66px] w-full border-0 bg-transparent px-1.5 py-1 text-ui-sm leading-relaxed text-foreground outline-none",
      },
      handleKeyDown: (_view, event) => {
        // ⌘/Ctrl+Enter 提交:光按 Enter 会和换行打架,而提示词经常要分行写。
        if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
          event.preventDefault();
          submitRef.current();
          return true;
        }
        return false;
      },
    },
    onUpdate: ({ editor: instance }) => {
      const next = instance.getText();
      emitted.current = next;
      onChange(next);
    },
  });

  React.useEffect(() => {
    if (!editor || value === emitted.current) return;
    emitted.current = value;
    editor.commands.setContent(
      value ? { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: value }] }] } : { type: "doc", content: [{ type: "paragraph" }] },
      { emitUpdate: false },
    );
  }, [value, editor]);

  return (
    <>
      <EditorContent editor={editor} />
      <menu.Portal className="fixed left-0 top-0 z-50 max-h-56 w-64 overflow-auto rounded-lg border border-border-strong bg-panel p-1 shadow-[var(--shadow-panel)]">
        {(asset, index) => (
          <button
            key={asset.id}
            type="button"
            className={cn(
              "flex w-full cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-left transition-colors",
              index === (menu.menu?.active ?? 0) ? "bg-secondary" : "hover:bg-secondary",
            )}
            // mousedown 会先让编辑器失焦,失焦又会收起菜单 —— 拦掉,让 click 有机会跑到。
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => menu.choose(asset)}
          >
            <img
              src={assetThumbnailUrl(asset.id)}
              alt=""
              className="h-7 w-10 shrink-0 rounded bg-[color-mix(in_srgb,var(--foreground)_6%,transparent)] object-cover"
            />
            <span className="min-w-0 flex-1 truncate text-ui-2xs text-foreground">
              {asset.name || asset.original_filename}
            </span>
            <span className="shrink-0 text-ui-2xs text-muted-foreground">{asset.kind}</span>
          </button>
        )}
      </menu.Portal>
    </>
  );
}
