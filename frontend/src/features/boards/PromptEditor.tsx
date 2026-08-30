import React from "react";
import {
  EditorContent,
  Node,
  NodeViewWrapper,
  ReactNodeViewRenderer,
  mergeAttributes,
  useEditor,
} from "@tiptap/react";
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
 * ## 选中的素材是正文里的一个 chip
 *
 * 它就长在句子里 ——「把 @创作者.png 里的人放到街上」读起来是一句话,而这正是用户写下 @
 * 时想说的。**chip 是原子节点**:整体选中、整体删除,退格不会把「创作者.png」咬掉半截
 * 变成一段没人认得的字。
 *
 * 提交时它一分为二:名字留在提示词里(有好几张图时,模型得知道你说的是哪张),素材本身
 * 进 source_assets。上面那排槽位是另一件事 —— 那里挂的是首帧/参考这种**有角色**的位置。
 */
/** 正文里的素材 chip。`atom: true` 是关键 —— 没有它光标能走进标签内部,退格就咬半截。 */
const AssetChip = Node.create({
  name: "assetRef",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  addAttributes: () => ({ assetId: { default: "" }, name: { default: "" } }),
  parseHTML: () => [{ tag: "span[data-asset-ref]" }],
  renderHTML: ({ HTMLAttributes }: { HTMLAttributes: Record<string, unknown> }) => [
    "span",
    mergeAttributes(HTMLAttributes, { "data-asset-ref": "" }),
  ],
  //: 序列化成**名字**而不是 id:editor.getText() 拿到的就是提示词该有的样子,
  //: 而 id 是给 source_assets 用的(从文档里另收,见 collect)。
  renderText: ({ node }: { node: { attrs: Record<string, unknown> } }) => String(node.attrs.name ?? ""),
  addNodeView: () =>
    ReactNodeViewRenderer(({ node }: { node: { attrs: Record<string, unknown> } }) => (
      <NodeViewWrapper as="span" className="inline-flex max-w-[180px] items-center gap-1 rounded-md bg-secondary px-1 py-0.5 align-baseline text-ui-2xs text-foreground">
        <img
          src={assetThumbnailUrl(String(node.attrs.assetId))}
          alt=""
          className="h-3.5 w-3.5 shrink-0 rounded-[3px] object-cover"
        />
        <span className="truncate">{String(node.attrs.name ?? "")}</span>
      </NodeViewWrapper>
    )),
});

/** 文档里所有 chip 引用到的素材 id,按出现顺序、去重。 */
export function collect(doc: { content?: unknown[] } | null): string[] {
  const found: string[] = [];
  const walk = (node: Record<string, unknown>) => {
    if (node.type === "assetRef") {
      const id = String((node.attrs as Record<string, unknown> | undefined)?.assetId ?? "");
      if (id && !found.includes(id)) found.push(id);
    }
    for (const child of (node.content as Record<string, unknown>[] | undefined) ?? []) walk(child);
  };
  if (doc) walk(doc as Record<string, unknown>);
  return found;
}

export function PromptEditor({
  value,
  onChange,
  placeholder,
  candidates,
  onSubmit,
  emptyHint,
}: {
  value: string;
  /** 正文变化。`assets` 是正文里 chip 引用到的素材 —— 提交时它们进 source_assets。 */
  onChange: (next: string, assets: string[]) => void;
  placeholder: string;
  /** `@` 能挑的素材。由调用方按「这个模型收得下什么」筛过。 */
  candidates: (query: string) => Asset[];
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
  const submitRef = React.useRef(onSubmit);
  submitRef.current = onSubmit;

  const menu = useSuggestionMenu<Asset>({
    emptyHint,
    sameItems: (a, b) => a.length === b.length && a.every((one, at) => one.id === b[at].id),
  });

  const editor = useEditor({
    extensions: [
      // 这是**一段提示词**,不是文档:标题、列表、加粗之类一概关掉。
      AssetChip,
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
          //: **`@` 前面是什么都认。** 插件默认(以及此前这里写的那张分隔符白名单)要求 `@`
          //: 跟在空格或分隔符后面 —— 于是「给@」打不出菜单,「给 @」才行。中文正文里本来就
          //: 不打空格,这条规则等于让这个功能在中文下时灵时不灵,而不灵的时候没有任何提示。
          //: 放开之后 `a@b` 这样的邮箱也会试着唤起,但它匹配不到任何东西,菜单自己就不显示 ——
          //: 「偶尔多算一次、什么都不弹」比「中文里一半时候用不了」轻得多。
          allowedPrefixes: null,
          items: ({ query }) => candidatesRef.current(query),
          command: ({ editor: instance, range, props }) => {
            const asset = props as unknown as Asset;
            //: 把那段 `@词` 换成一个 chip,并在后面补一个空格 —— 不补的话光标紧贴着原子节点,
            //: 接着打字会被当成还在挑素材。
            instance
              .chain()
              .focus()
              .deleteRange(range)
              .insertContent([
                { type: "assetRef", attrs: { assetId: asset.id, name: asset.name || asset.original_filename || "" } },
                { type: "text", text: " " },
              ])
              .run();
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
      onChange(next, collect(instance.getJSON() as { content?: unknown[] }));
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
