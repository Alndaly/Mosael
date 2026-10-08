import React from "react";
import { Music2 } from "lucide-react";
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

import { assetThumbnailUrl, type Asset, type EntitySummary } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Truncate } from "@/components/ui/truncate";
import type { MessageKey } from "@/app/messages";
import type { MediaKind } from "@/features/boards/boardNodes";
import { RefSuggestion } from "@/components/app/refSuggestion";
import { useSuggestionMenu } from "@/components/app/suggestionMenu";
import { useExternalContent } from "@/components/app/useExternalContent";
import { isSubmitChord } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";
import { EntityMentionRow, EntityThumb } from "@/features/entities/EntityMention";
import { entityDisplayName } from "@/features/entities/entityMeta";

export type PromptDocument = JSONContent;

/**
 * `@` 菜单里的一条:素材库里的一份素材,或者资产库里的一个资产(ADR 0027)。**一个菜单、一套键盘和筛选**,
 * 两种东西各自长成自己的样子、落成自己的 chip —— 不另起一个「@ 资产」菜单。
 */
export type MentionItem =
  | { type: "asset"; id: string; asset: MentionAsset }
  | { type: "entity"; id: string; entity: EntitySummary };

/** `@` 菜单里一份素材要的那几样:素材库的卡片就够(名字、种类、缩略图按 id 取)。 */
export type MentionAsset = Pick<Asset, "id" | "name" | "original_filename" | "kind">;

/** 一段纯文本的提示词文档(没有素材 chip)。 */
export function textDocument(value: string): PromptDocument {
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
/** 这一行要不要先画一个分组标题:上一条和它不在同一组时画。分组缺省是「连进来的 / 其余」,可以另给一个分法。 */
export function groupHeadAt<T extends { id: string }>(
  items: T[],
  index: number,
  linked: Set<string>,
  groupOf: (item: T) => string = (item) => (linked.has(item.id) ? "linked" : "library"),
): boolean {
  if (index === 0) return true;
  return groupOf(items[index]) !== groupOf(items[index - 1]);
}

/** 一条候选归哪一组:连进这一格的(素材或资产格)排最前,其次资产库,最后素材库。 */
export function mentionGroup(item: MentionItem, linked: Set<string>): "linked" | "entities" | "library" {
  if (linked.has(item.id)) return "linked";
  return item.type === "entity" ? "entities" : "library";
}

const GROUP_ORDER = { linked: 0, entities: 1, library: 2 } as const;
const GROUP_TITLE: Record<"linked" | "entities" | "library", MessageKey> = {
  linked: "boardPickLinkedGroup",
  entities: "boardPickEntitiesGroup",
  library: "boardPickLibrary",
};

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
        <Truncate>{String(node.attrs.name ?? "")}</Truncate>
      </NodeViewWrapper>
    )),
});

/** 正文里的资产 chip(ADR 0027)。序列化成资产的名字 —— 「张三站在街口」读起来是一句话;
 *  资产本身(提示词描述、参考图)由服务端按 `entity_ids` 挂上,见 collectEntities。 */
const EntityChip = Node.create({
  name: "entityRef",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  addAttributes: () => ({ entityId: { default: "" }, name: { default: "" }, kind: { default: "" }, cover: { default: "" } }),
  parseHTML: () => [{ tag: "span[data-entity-ref]" }],
  renderHTML: ({ HTMLAttributes }: { HTMLAttributes: Record<string, unknown> }) => [
    "span",
    mergeAttributes(HTMLAttributes, { "data-entity-ref": "" }),
  ],
  renderText: ({ node }: { node: { attrs: Record<string, unknown> } }) => String(node.attrs.name ?? ""),
  addNodeView: () =>
    ReactNodeViewRenderer(({ node }: { node: { attrs: Record<string, unknown> } }) => (
      <NodeViewWrapper
        as="span"
        data-entity-ref=""
        data-entity-id={String(node.attrs.entityId)}
        className="inline-flex max-w-[180px] items-center gap-1 rounded-md bg-accent px-1 py-0.5 align-baseline text-ui-2xs text-foreground"
      >
        <EntityThumb
          entity={{ kind: String(node.attrs.kind || "character") as EntitySummary["kind"], cover_asset_id: String(node.attrs.cover || "") || null }}
          className="h-3.5 w-3.5 rounded-[3px]"
        />
        <Truncate>{String(node.attrs.name ?? "")}</Truncate>
      </NodeViewWrapper>
    )),
});

/** 文档里所有资产 chip 引用到的资产 id,按出现顺序、去重。 */
export function collectEntities(doc: { content?: unknown[] } | null): string[] {
  const found: string[] = [];
  const walk = (node: Record<string, unknown>) => {
    if (node.type === "entityRef") {
      const id = String((node.attrs as Record<string, unknown> | undefined)?.entityId ?? "");
      if (id && !found.includes(id)) found.push(id);
    }
    for (const child of (node.content as Record<string, unknown>[] | undefined) ?? []) walk(child);
  };
  if (doc) walk(doc as Record<string, unknown>);
  return found;
}

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
  label,
  candidates,
  onSubmit,
  emptyHint,
  linked,
  entities,
  linkedEntities,
}: {
  value: string;
  /** 节点表单里保存的 TipTap JSON；没有时按旧版纯文本打开。 */
  document?: PromptDocument;
  /** 正文变化。`assets` 是正文里 chip 引用到的素材 —— 提交时它们进 source_assets;`entityIds` 是 @ 到的资产。 */
  onChange: (next: string, assets: string[], document: PromptDocument, entityIds: string[]) => void;
  placeholder: string;
  /** 读屏念的名字。不给就用占位提示(tiptap 的占位只是一个 data 属性,读屏不念)。 */
  label?: string;
  /**
   * `@` 能挑的素材:由调用方按「这个模型收得下什么」在服务端搜(素材库分了页,不再整个拿回来在这里筛)。
   * 插件每次 query 变了问一次,等它回来再画菜单。
   */
  candidates: (query: string) => Promise<MentionAsset[]>;
  /** ⌘/Ctrl+Enter。 */
  onSubmit: () => void;
  /** 一个候选都没有时说的那句话;返回空串就什么都不弹。 */
  emptyHint: () => string;
  /** 连进这个节点的那几份素材。它们排在最前面 —— 「刚接进来的那张」是最可能要指的。 */
  linked?: string[];
  /** `@` 能挑的资产(ADR 0027)。不给就只挑素材。 */
  entities?: (query: string) => EntitySummary[];
  /** 连进这个节点的资产格引用的资产 —— 和连进来的素材一起排在最前。 */
  linkedEntities?: string[];
}) {
  //: 最后一次自己发出去的值。外面改了(上游便签填进来、撤销)才回灌,否则每敲一个字都会被
  //: prop 回流重建文档,光标跳到开头。
  const initialDocument = document ?? textDocument(value);
  const emitted = React.useRef({ value, document: JSON.stringify(initialDocument) });
  //: 插件的回调在创建时一次性装好,拿不到后续渲染的闭包 —— 用 ref 兜住当前值。
  const candidatesRef = React.useRef(candidates);
  candidatesRef.current = candidates;
  const entitiesRef = React.useRef(entities);
  entitiesRef.current = entities;
  const submitRef = React.useRef(onSubmit);
  submitRef.current = onSubmit;
  const t = useI18n();

  //: 筛选**只作用于看得见的这一份**。放进 candidates() 的话按下去毫无反应:插件只在
  //: query / 光标位置变了才重新取候选,而按一下筛选钮这两样都没变(见 useSuggestionMenu 的 view)。
  const [filter, setFilter] = React.useState<"all" | "linked" | "entity" | MediaKind>("all");
  const linkedIds = React.useMemo(() => new Set([...(linked ?? []), ...(linkedEntities ?? [])]), [linked, linkedEntities]);

  const passes = React.useCallback(
    (one: MentionItem) =>
      filter === "all"
        ? true
        : filter === "linked"
          ? linkedIds.has(one.id)
          : filter === "entity"
            ? one.type === "entity"
            : one.type === "asset" && one.asset.kind === filter,
    [filter, linkedIds],
  );

  //: 先按筛选留下,再按组排(连进来的 → 资产 → 素材),最后截断。**排序在截断之前** —— 反过来的话,
  //: 连进来的那张要是排在第 20 位,截完就没了,而它恰恰是最该出现的一条。
  const view = React.useCallback(
    (items: MentionItem[]) =>
      items
        .filter(passes)
        .map((one, at) => ({ one, at }))
        .sort((a, b) => GROUP_ORDER[mentionGroup(a.one, linkedIds)] - GROUP_ORDER[mentionGroup(b.one, linkedIds)] || a.at - b.at)
        .map(({ one }) => one)
        .slice(0, LIMIT),
    [passes, linkedIds],
  );

  const menu = useSuggestionMenu<MentionItem>({
    emptyHint,
    sameItems: (a, b) => a.length === b.length && a.every((one, at) => one.id === b[at].id),
    view,
  });

  //: 表头读的是**没过筛选的那一份**(menu.all)—— 读过筛选的会让筛选钮自己把自己藏起来:
  //: 点「视频」之后列表里只剩视频,「图片」那个钮就消失了,再也点不回去。
  const kinds = React.useMemo(() => {
    const set = new Set(menu.all.flatMap((one) => (one.type === "asset" ? [one.asset.kind] : [])));
    return (["image", "video", "audio"] as const).filter((kind) => set.has(kind));
  }, [menu.all]);
  const hasEntities = menu.all.some((one) => one.type === "entity");
  //: 只有一类素材、又没有资产时,不给类型钮、行上不标类型 —— 它和「全部」是同一份东西。
  const onlyKind = kinds.length === 1 && !hasEntities ? kinds[0] : null;
  const hasLinked = menu.all.some((one) => linkedIds.has(one.id));
  const chips = React.useMemo(
    () => [
      { key: "all" as const, label: t("boardPickAll") },
      ...(hasLinked ? [{ key: "linked" as const, label: t("boardPickLinked") }] : []),
      ...(hasEntities && kinds.length > 0 ? [{ key: "entity" as const, label: t("boardPickEntities") }] : []),
      ...(kinds.length > 1 || (kinds.length === 1 && hasEntities) ? kinds.map((kind) => ({ key: kind, label: t(KIND_LABEL[kind]) })) : []),
    ],
    [hasLinked, hasEntities, kinds, t],
  );
  //: 被截掉了多少条。按**筛完之后**的总数算 —— 拿原始总数减,会在筛过之后报一个虚高的数字。
  const hidden = React.useMemo(() => Math.max(0, menu.all.filter(passes).length - LIMIT), [menu.all, passes]);

  const editor = useEditor({
    extensions: [
      // 这是**一段提示词**,不是文档:标题、列表、加粗之类一概关掉。
      AssetChip,
      EntityChip,
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
          items: async ({ query }): Promise<MentionItem[]> => {
            const entities = (entitiesRef.current?.(query) ?? []).map((entity) => ({ type: "entity" as const, id: entity.id, entity }));
            //: 搜素材失败(断网、后端在重启)只是少了素材那一段,资产照样列。
            const assets = await candidatesRef.current(query).catch((): MentionAsset[] => []);
            return [...entities, ...assets.map((asset) => ({ type: "asset" as const, id: asset.id, asset }))];
          },
          command: ({ editor: instance, range, props }) => {
            const item = props as unknown as MentionItem;
            //: 把那段 `@词` 换成一个 chip,并在后面补一个空格 —— 不补的话光标紧贴着原子节点,
            //: 接着打字会被当成还在挑素材。
            const chip =
              item.type === "entity"
                ? {
                    type: "entityRef",
                    attrs: {
                      entityId: item.entity.id,
                      name: entityDisplayName(item.entity),
                      kind: item.entity.kind,
                      cover: item.entity.cover_asset_id ?? "",
                    },
                  }
                : { type: "assetRef", attrs: { assetId: item.asset.id, name: item.asset.name || item.asset.original_filename || "" } };
            instance
              .chain()
              .focus()
              .deleteRange(range)
              .insertContent([chip, { type: "text", text: " " }])
              .run();
          },
          render: menu.render,
        },
      }),
    ],
    content: initialDocument,
    editorProps: {
      attributes: {
        // nodrag:这东西活在画布上,不挂的话在里面选文字会变成拖画布。
        // **不挂 nowheel**:它只有 min-height、没有上限,内容多了是自己长高而不是滚动 ——
        // 没有东西可滚,却会把触控板的两指平移在这块区域上截停(见 CommentComposer 那条用例)。
        class:
          "nodrag min-h-[66px] w-full border-0 bg-transparent px-1.5 py-1 text-ui-sm leading-relaxed text-foreground outline-none",
        //: 可编辑的 div 读屏只念「可编辑文本」:名字、角色、多行都得自己写上(design/editorNames.test.ts)。
        "aria-label": label || placeholder,
        role: "textbox",
        "aria-multiline": "true",
      },
      handleKeyDown: (_view, event) => {
        // ⌘/Ctrl+Enter 提交:光按 Enter 会和换行打架,而提示词经常要分行写(和 AI Studio 的生成框同一个键,见 isSubmitChord)。
        if (isSubmitChord(event)) {
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
      onChange(next, collect(nextDocument as { content?: unknown[] }), nextDocument, collectEntities(nextDocument as { content?: unknown[] }));
    },
  });

  //: 组词期间不回灌(见 useExternalContent)。
  useExternalContent(editor, (instance) => {
    const nextDocument = document ?? textDocument(value);
    const serialized = JSON.stringify(nextDocument);
    if (value === emitted.current.value && serialized === emitted.current.document) return;
    emitted.current = { value, document: serialized };
    instance.commands.setContent(nextDocument, { emitUpdate: false });
  }, [value, document]);

  return (
    <>
      <EditorContent editor={editor} />
      <menu.Portal
        className="fixed left-0 top-0 z-50 max-h-[min(360px,calc(100dvh-16px))] w-[360px] max-w-[calc(100vw-16px)] rounded-xl p-1.5"
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
                      ? "bg-action text-action-foreground"
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
        {(item, index) => (
          <React.Fragment key={`${item.type}:${item.id}`}>
            {/* 分组标题**由列表自己长出来**,不另存一份结构:上一条和这一条不在同一组时画一行。
                「刚连进来的那张」是最可能要指的,所以它单独成组、排在最前;资产库在素材库前面。 */}
            {groupHeadAt(menu.menu?.items ?? [], index, linkedIds, (one) => mentionGroup(one, linkedIds)) && (
              <div className="px-1.5 pb-0.5 pt-1 text-ui-2xs font-semibold text-muted-foreground">
                {t(GROUP_TITLE[mentionGroup(item, linkedIds)])}
              </div>
            )}
            <button
              type="button"
              data-mention={item.type}
              className={cn(
                "flex w-full cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-left transition-colors",
                index === (menu.menu?.active ?? 0) ? "bg-secondary" : "hover:bg-secondary",
              )}
              // mousedown 会先让编辑器失焦,失焦又会收起菜单 —— 拦掉,让 click 有机会跑到。
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => menu.choose(item)}
            >
              {item.type === "entity" ? (
                <EntityMentionRow entity={item.entity} />
              ) : (
                <>
                  {item.asset.kind === "audio" ? (
                    <span className="grid h-8 w-10 shrink-0 place-items-center rounded bg-control text-muted-foreground"><Music2 size={16} aria-hidden /></span>
                  ) : (
                    <img src={assetThumbnailUrl(item.asset.id)} alt="" className="h-8 w-10 shrink-0 rounded bg-control object-cover" />
                  )}
                  <Truncate className="flex-1 text-ui-xs text-foreground">
                    {item.asset.name || item.asset.original_filename}
                  </Truncate>
                  {/* **只有一类可选时不标类型。** 每行都写一遍「image」是纯噪音 —— 它没有回答
                      任何问题,而列表里本来就只有这一类。 */}
                  {!onlyKind && (
                    <span className="shrink-0 text-ui-2xs text-muted-foreground">
                      {t(KIND_LABEL[item.asset.kind as MediaKind] ?? "boardKindImage")}
                    </span>
                  )}
                </>
              )}
            </button>
          </React.Fragment>
        )}
      </menu.Portal>
    </>
  );
}
