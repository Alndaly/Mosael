import React from "react";
import {
  EditorContent,
  type JSONContent,
  Node,
  NodeViewWrapper,
  ReactNodeViewRenderer,
  mergeAttributes,
  useEditor,
} from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";

import { assetThumbnailUrl, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import type { MessageKey } from "@/app/messages";
import type { MediaKind } from "@/features/boards/boardNodes";
import { RefSuggestion } from "@/components/app/refSuggestion";
import { useSuggestionMenu } from "@/components/app/suggestionMenu";
import { cn } from "@/lib/utils";

export type PromptDocument = JSONContent;

function textDocument(value: string): PromptDocument {
  return value
    ? { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: value }] }] }
    : { type: "doc", content: [{ type: "paragraph" }] };
}

/**
 * 升级只有 prompt + mentioned_asset_ids 的旧节点。
 *
 * chip 的 renderText 本来就写入素材名，所以可以用 id 找回名字，再在原位置恢复原子节点。
 * 找不到素材或名字时保持原文字，不凭空把引用塞到句首。
 */
export function restorePromptDocument(
  value: string,
  mentionedAssetIds: string[],
  assets: Pick<Asset, "id" | "name" | "original_filename">[],
): PromptDocument {
  const references = mentionedAssetIds
    .map((id) => {
      const asset = assets.find((one) => one.id === id);
      const name = asset?.name || asset?.original_filename || "";
      return name ? { id, name } : null;
    })
    .filter((one): one is { id: string; name: string } => Boolean(one));
  if (!value || references.length === 0) return textDocument(value);

  const content: JSONContent[] = [];
  let cursor = 0;
  while (cursor < value.length) {
    const next = references
      .map((reference) => ({ reference, at: value.indexOf(reference.name, cursor) }))
      .filter((match) => match.at >= 0)
      .sort((a, b) => a.at - b.at || b.reference.name.length - a.reference.name.length)[0];
    if (!next) {
      content.push({ type: "text", text: value.slice(cursor) });
      break;
    }
    if (next.at > cursor) content.push({ type: "text", text: value.slice(cursor, next.at) });
    content.push({
      type: "assetRef",
      attrs: { assetId: next.reference.id, name: next.reference.name },
    });
    cursor = next.at + next.reference.name.length;
  }
  return { type: "doc", content: [{ type: "paragraph", ...(content.length ? { content } : {}) }] };
}

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
/** 这一行要不要先画一个分组标题:上一条和它不在同一组时画。 */
export function groupHeadAt(items: { id: string }[], index: number, linked: Set<string>): boolean {
  if (index === 0) return true;
  return linked.has(items[index].id) !== linked.has(items[index - 1].id);
}

/** 类型在界面上叫什么。和画布节点上的标签同一份 —— 那边叫「视频」这边就不能叫「video」。 */
const KIND_LABEL: Record<string, MessageKey> = {
  image: "boardKindImage",
  video: "boardKindVideo",
  audio: "boardKindAudio",
};

/** 菜单里最多摆几条。再多就该靠打字缩范围,而不是滚一整屏。 */
const LIMIT = 12;

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
      <NodeViewWrapper
        as="span"
        data-asset-ref=""
        data-asset-id={String(node.attrs.assetId)}
        className="inline-flex max-w-[180px] items-center gap-1 rounded-md bg-secondary px-1 py-0.5 align-baseline text-ui-2xs text-foreground"
      >
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
  document,
  onChange,
  placeholder,
  candidates,
  onSubmit,
  emptyHint,
  linked,
}: {
  value: string;
  /** 节点表单里保存的 TipTap JSON；没有时按旧版纯文本打开。 */
  document?: PromptDocument;
  /** 正文变化。`assets` 是正文里 chip 引用到的素材 —— 提交时它们进 source_assets。 */
  onChange: (next: string, assets: string[], document: PromptDocument) => void;
  placeholder: string;
  /** `@` 能挑的素材。由调用方按「这个模型收得下什么」筛过。 */
  candidates: (query: string) => Asset[];
  /** ⌘/Ctrl+Enter。 */
  onSubmit: () => void;
  /** 一个候选都没有时说的那句话;返回空串就什么都不弹。 */
  emptyHint: () => string;
  /** 连进这个节点的那几份素材。它们排在最前面 —— 「刚接进来的那张」是最可能要指的。 */
  linked?: string[];
}) {
  //: 最后一次自己发出去的值。外面改了(上游便签填进来、撤销)才回灌,否则每敲一个字都会被
  //: prop 回流重建文档,光标跳到开头。
  const initialDocument = document ?? textDocument(value);
  const emitted = React.useRef({ value, document: JSON.stringify(initialDocument) });
  //: 插件的回调在创建时一次性装好,拿不到后续渲染的闭包 —— 用 ref 兜住当前值。
  const candidatesRef = React.useRef(candidates);
  candidatesRef.current = candidates;
  const submitRef = React.useRef(onSubmit);
  submitRef.current = onSubmit;
  const t = useI18n();

  //: 筛选**只作用于看得见的这一份**。放进 candidates() 的话按下去毫无反应:插件只在
  //: query / 光标位置变了才重新取候选,而按一下筛选钮这两样都没变(见 useSuggestionMenu 的 view)。
  const [filter, setFilter] = React.useState<"all" | "linked" | MediaKind>("all");
  const linkedIds = React.useMemo(() => new Set(linked ?? []), [linked]);

  //: 先按筛选留下,再把连进来的提到前面,最后截断。**排序在截断之前** —— 反过来的话,
  //: 连进来的那张要是排在第 20 位,截完就没了,而它恰恰是最该出现的一条。
  const view = React.useCallback(
    (items: Asset[]) => {
      const kept = items.filter((one) =>
        filter === "all" ? true : filter === "linked" ? linkedIds.has(one.id) : one.kind === filter,
      );
      const linkedFirst = [
        ...kept.filter((one) => linkedIds.has(one.id)),
        ...kept.filter((one) => !linkedIds.has(one.id)),
      ];
      return linkedFirst.slice(0, LIMIT);
    },
    [filter, linkedIds],
  );

  const menu = useSuggestionMenu<Asset>({
    emptyHint,
    sameItems: (a, b) => a.length === b.length && a.every((one, at) => one.id === b[at].id),
    view,
  });

  //: 表头读的是**没过筛选的那一份**(menu.all)—— 读过筛选的会让筛选钮自己把自己藏起来:
  //: 点「视频」之后列表里只剩视频,「图片」那个钮就消失了,再也点不回去。
  const kinds = React.useMemo(() => {
    const set = new Set(menu.all.map((one) => one.kind));
    return (["image", "video", "audio"] as const).filter((kind) => set.has(kind));
  }, [menu.all]);
  const onlyKind = kinds.length === 1 ? kinds[0] : null;
  const hasLinked = menu.all.some((one) => linkedIds.has(one.id));
  const chips = React.useMemo(
    () => [
      { key: "all" as const, label: t("boardPickAll") },
      ...(hasLinked ? [{ key: "linked" as const, label: t("boardPickLinked") }] : []),
      //: 只有一类时不给类型钮 —— 它和「全部」是同一份东西。
      ...(onlyKind ? [] : kinds.map((kind) => ({ key: kind, label: t(KIND_LABEL[kind]) }))),
    ],
    [hasLinked, kinds, onlyKind, t],
  );
  //: 被截掉了多少条。按**筛完之后**的总数算 —— 拿原始总数减,会在筛过之后报一个虚高的数字。
  const hidden = React.useMemo(() => {
    const kept = menu.all.filter((one) =>
      filter === "all" ? true : filter === "linked" ? linkedIds.has(one.id) : one.kind === filter,
    );
    return Math.max(0, kept.length - LIMIT);
  }, [menu.all, filter, linkedIds]);

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
    content: initialDocument,
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
      const nextDocument = instance.getJSON() as PromptDocument;
      emitted.current = { value: next, document: JSON.stringify(nextDocument) };
      onChange(next, collect(nextDocument as { content?: unknown[] }), nextDocument);
    },
  });

  React.useEffect(() => {
    if (!editor) return;
    const nextDocument = document ?? textDocument(value);
    const serialized = JSON.stringify(nextDocument);
    if (value === emitted.current.value && serialized === emitted.current.document) return;
    emitted.current = { value, document: serialized };
    editor.commands.setContent(nextDocument, { emitUpdate: false });
  }, [value, document, editor]);

  return (
    <>
      <EditorContent editor={editor} />
      <menu.Portal
        className="fixed left-0 top-0 z-50 max-h-64 w-72 rounded-lg border border-border-strong bg-panel p-1 shadow-[var(--shadow-panel)]"
        header={
          <div className="grid gap-1 border-b border-border px-1 pb-1.5 pt-0.5">
            {/* 快捷分类。**只摆真的有东西的那几档** —— 一个按下去必然空的筛选钮,
                比没有这个钮更让人困惑。 */}
            <div className="flex flex-wrap items-center gap-1">
              {chips.map((chip) => (
                <button
                  key={chip.key}
                  type="button"
                  className={cn(
                    "cursor-pointer rounded-full border-0 px-1.5 py-0.5 text-ui-2xs transition-colors",
                    filter === chip.key
                      ? "bg-primary text-primary-foreground"
                      : "bg-secondary text-muted-foreground hover:text-foreground",
                  )}
                  //: 和列表项同一个道理:mousedown 会让编辑器失焦,失焦就收菜单。
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => setFilter(chip.key)}
                >
                  {chip.label}
                </button>
              ))}
            </div>
            {/* **说清楚为什么只有这一类。** 一个只收图片的模型下,视频不出现在列表里是对的,
                但界面此前一个字都没说 —— 用户只会觉得"我的视频呢"。 */}
            {onlyKind && (
              <span className="text-ui-2xs text-muted-foreground">
                {t("boardPickOnlyKind").replace("{kind}", t(KIND_LABEL[onlyKind]))}
              </span>
            )}
          </div>
        }
        footer={
          hidden > 0 ? (
            <div className="border-t border-border px-2 pb-0.5 pt-1 text-ui-2xs text-muted-foreground">
              {t("boardPickMore").replace("{n}", String(hidden))}
            </div>
          ) : null
        }
      >
        {(asset, index) => (
          <React.Fragment key={asset.id}>
            {/* 分组标题**由列表自己长出来**,不另存一份结构:上一条和这一条不在同一组时画一行。
                「刚连进来的那张」是最可能要指的,所以它单独成组、排在最前。 */}
            {groupHeadAt(menu.menu?.items ?? [], index, linkedIds) && (
              <div className="px-1.5 pb-0.5 pt-1 text-ui-2xs font-semibold text-muted-foreground">
                {t(linkedIds.has(asset.id) ? "boardPickLinkedGroup" : "boardPickLibrary")}
              </div>
            )}
            <button
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
              {/* **只有一类可选时不标类型。** 每行都写一遍「image」是纯噪音 —— 它没有回答
                  任何问题,而列表里本来就只有这一类。 */}
              {!onlyKind && (
                <span className="shrink-0 text-ui-2xs text-muted-foreground">
                  {t(KIND_LABEL[asset.kind as MediaKind] ?? "boardKindImage")}
                </span>
              )}
            </button>
          </React.Fragment>
        )}
      </menu.Portal>
    </>
  );
}
