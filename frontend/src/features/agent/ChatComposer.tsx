import React from "react";
import { EditorContent, type JSONContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";

import { useI18n } from "@/app/preferences";
import { RefSuggestion } from "@/components/app/refSuggestion";
import { useSuggestionMenu } from "@/components/app/suggestionMenu";
import { ReferenceChip, ReferenceThumb, REFERENCE_NODE } from "@/features/agent/ReferenceChip";
import { REFERENCE_META, searchReferences, type AgentReference, type ReferenceKind } from "@/features/agent/references";
import { cn } from "@/lib/utils";

/** 菜单里最多摆几条。再多就该靠打字缩范围,而不是滚一整屏(同画布的提示词框)。 */
const LIMIT = 12;

/** 一次发送的内容:给模型看的那句话 + 结构化的引用。 */
export interface ChatDraft {
  /** `editor.getText()` —— 引用在里面是 `@名字`。 */
  text: string;
  /** 正文里出现过的引用,按出现顺序、去重。id 只走这里。 */
  references: AgentReference[];
  /** 原样的编辑器文档。落库之后气泡照它渲染,引用**仍然是胶囊**而不是一串字。 */
  document: JSONContent;
}

/** 从文档里收出所有引用,按出现顺序去重。 */
export function collectReferences(document: JSONContent | undefined): AgentReference[] {
  const out: AgentReference[] = [];
  const seen = new Set<string>();
  const walk = (node: JSONContent | undefined) => {
    if (!node) return;
    if (node.type === REFERENCE_NODE) {
      const attrs = (node.attrs ?? {}) as { kind?: string; refId?: string; name?: string };
      const key = `${attrs.kind}:${attrs.refId}`;
      if (attrs.refId && !seen.has(key)) {
        seen.add(key);
        out.push({ kind: (attrs.kind ?? "asset") as ReferenceKind, id: attrs.refId, name: attrs.name ?? "" });
      }
    }
    for (const child of node.content ?? []) walk(child);
  };
  walk(document);
  return out;
}

/**
 * 这一下回车是不是「把消息发出去」。
 *
 * **菜单开着时不是** —— 那时回车归菜单(选中高亮的那一条)。这件事必须显式判断:
 * ProseMirror 解 `handleKeyDown` 时**先问视图自己的 props、再问各个插件**,也就是说
 * 编辑器上挂的这个函数排在 suggestion 插件前面。不让路的话,`@` 菜单里按回车永远是发送,
 * 而不是选中:菜单看着能用、上下键也走得动,就是选不中。
 * (画布那份提示词框用的是 ⌘/Ctrl+Enter 提交,天生不撞;聊天的习惯是光按回车,所以得让路。)
 *
 * Shift+回车是换行;输入法组字中的回车是选词,两者都不发送。
 */
export function sendsOnEnter(
  event: Pick<KeyboardEvent, "key" | "shiftKey" | "isComposing">,
  menuOpen: boolean,
): boolean {
  if (menuOpen) return false;
  return event.key === "Enter" && !event.shiftKey && !event.isComposing;
}

export const emptyDocument: JSONContent = { type: "doc", content: [{ type: "paragraph" }] };

/**
 * 文档 → 发给模型的那句话。引用序列化成 `@名字`(和 ReferenceChip 的 renderText 同一约定)。
 *
 * **不借编辑器实例来做这件事**:发送时手上只有 state 里的文档,而编辑器可能还没建、
 * 或者已经被清空。一个纯函数在哪儿都能调,也测得动。
 */
export function documentText(document: JSONContent | undefined): string {
  const parts: string[] = [];
  const walk = (node: JSONContent | undefined) => {
    if (!node) return;
    if (node.type === REFERENCE_NODE) {
      parts.push(`@${String((node.attrs as { name?: string } | undefined)?.name ?? "")}`);
      return;
    }
    if (node.type === "text") {
      parts.push(node.text ?? "");
      return;
    }
    if (node.type === "hardBreak") {
      parts.push("\n");
      return;
    }
    const children = node.content ?? [];
    children.forEach(walk);
    // 段落之间是换行 —— 用户敲的空行是他排的版,拼成一坨会把它抹掉。
    if (node.type === "paragraph") parts.push("\n");
  };
  walk(document);
  return parts.join("").replace(/\n+$/, "");
}

/**
 * 智能体聊天的输入框。
 *
 * **为什么不是 textarea。** 此前是,而附件靠往正文里拼一段 `[附件 asset_id=… 名称=…]`
 * 的标记、发出去之后再用正则拆回来渲染。那条路只对附件成立,而且中间那段字一旦被用户
 * 编辑过就散架 —— 标记是文本,文本是可以被删掉半个的。画布那边(PromptEditor)早就走的是
 * 另一条:引用是**原子节点**,文档以 JSON 存下来。这里把那条搬过来,并且扩到四类对象。
 *
 * 分工照旧:`@` 什么时候触发、按键路由给谁,归 ProseMirror 插件(它懂输入法);
 * 菜单长什么样归 React(见 refSuggestion / suggestionMenu 里那两段说明)。
 */
export function ChatComposer({
  workspaceId,
  value,
  onChange,
  onSubmit,
  onPaste,
  placeholder,
  className,
  search = searchReferences,
}: {
  workspaceId: string;
  value: JSONContent;
  onChange: (next: JSONContent) => void;
  /** 回车发送(Shift+回车换行)。拿到的就是要发出去的那一份。 */
  onSubmit: (draft: ChatDraft) => void;
  onPaste?: (event: React.ClipboardEvent) => boolean;
  placeholder?: string;
  className?: string;
  /** 候选从哪儿来。默认问工作区;**留这个口子是为了测得动** —— 菜单的排版和键盘行为
   *  不该为了验证一次就得起一个后端。 */
  search?: (workspaceId: string, query: string, limit: number) => Promise<AgentReference[]>;
}) {
  const t = useI18n();
  //: 插件的回调在创建时一次性装好,拿不到后续渲染的闭包 —— 用 ref 兜住当前值(同画布)。
  const workspaceRef = React.useRef(workspaceId);
  workspaceRef.current = workspaceId;
  const submitRef = React.useRef(onSubmit);
  submitRef.current = onSubmit;
  const searchRef = React.useRef(search);
  searchRef.current = search;
  //: handleKeyDown 在创建时装好,闭包住的是那一刻的状态 —— 用 ref 读"菜单现在开着没有"。
  const menuOpenRef = React.useRef(false);

  const menu = useSuggestionMenu<AgentReference>({
    emptyHint: () => t("boardNoAssetsToMention"),
    sameItems: (a, b) => a.length === b.length && a.every((one, at) => one.id === b[at].id),
    view: (items) => items.slice(0, LIMIT),
  });

  menuOpenRef.current = Boolean(menu.menu);

  const emitted = React.useRef(JSON.stringify(value));
  const editor = useEditor({
    extensions: [
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
      Placeholder.configure({ placeholder: placeholder ?? "" }),
      ReferenceChip,
      RefSuggestion.configure({
        suggestion: {
          char: "@",
          //: **`@` 前面是什么都认**。默认要求它跟在空格后面,而中文正文里不打空格 ——
          //: 那条规则等于让这个功能在中文下时灵时不灵(画布那边同一段说明)。
          allowedPrefixes: null,
          items: ({ query }) => searchRef.current(workspaceRef.current, query, LIMIT * 4),
          command: ({ editor: instance, range, props }) => {
            const picked = props as unknown as AgentReference;
            //: 换成胶囊之后补一个空格 —— 不补的话光标紧贴原子节点,接着打字会被当成还在挑。
            instance
              .chain()
              .focus()
              .deleteRange(range)
              .insertContent([
                { type: REFERENCE_NODE, attrs: { kind: picked.kind, refId: picked.id, name: picked.name } },
                { type: "text", text: " " },
              ])
              .run();
          },
          render: menu.render,
        },
      }),
    ],
    content: value,
    editorProps: {
      attributes: {
        class: cn(
          "max-h-[220px] min-h-9 w-full overflow-y-auto border-0 bg-transparent px-0.5 pb-1.5 pt-0.5 text-ui-md leading-[1.55] text-foreground outline-none",
          className,
        ),
      },
      handlePaste: (_view, event) => (onPaste ? onPaste(event as unknown as React.ClipboardEvent) : false),
      handleKeyDown: (_view, event) => {
        if (!sendsOnEnter(event, menuOpenRef.current)) return false;
        const instance = editorRef.current;
        if (!instance) return false;
        event.preventDefault();
        const document = instance.getJSON();
        submitRef.current({ text: instance.getText().trim(), references: collectReferences(document), document });
        return true;
      },
    },
    onUpdate: ({ editor: instance }) => {
      const next = instance.getJSON();
      emitted.current = JSON.stringify(next);
      onChange(next);
    },
  });
  const editorRef = React.useRef(editor);
  editorRef.current = editor;

  //: 外面改了(清空、把说的话填进来)才回灌 —— 自己发出去的那一版不跟,否则每敲一个字
  //: 都会被 prop 回流重建文档,光标跳到开头(画布那边同一个处理)。
  React.useEffect(() => {
    const incoming = JSON.stringify(value);
    if (!editor || incoming === emitted.current) return;
    emitted.current = incoming;
    editor.commands.setContent(value, { emitUpdate: false });
  }, [editor, value]);

  return (
    <>
      <EditorContent editor={editor} />
      {/* 版式照画布那份提示词框(features/boards/PromptEditor):同样的宽度、同样的行高、
          同样的分组标题。同一个动作在两个地方长得不一样,用户会以为是两个不同的东西。 */}
      <menu.Portal className="fixed left-0 top-0 z-50 max-h-[min(360px,calc(100dvh-16px))] w-[360px] max-w-[calc(100vw-16px)] rounded-xl p-1.5">
        {(item, index) => (
          <React.Fragment key={`${item.kind}:${item.id}`}>
            {/* 分组标题**由列表自己长出来**,不另存一份结构:上一条和这一条不同类时画一行。
                候选是按类成段给的(见 searchReferences),所以这一行判据只看"和上一条同不同类"。 */}
            {(index === 0 || (menu.menu?.items ?? [])[index - 1]?.kind !== item.kind) && (
              <div className="px-1.5 pb-0.5 pt-1 text-ui-2xs font-semibold text-muted-foreground">
                {t(REFERENCE_META[item.kind].labelKey)}
              </div>
            )}
            <button
              type="button"
              className={cn(
                "flex w-full cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-left transition-colors",
                index === (menu.menu?.active ?? 0) ? "bg-secondary" : "hover:bg-secondary",
              )}
              //: mousedown 会先让编辑器失焦,失焦又会收起菜单 —— 拦掉,让 click 有机会跑到。
              //: (画布那份踩过同一脚,注释也在那儿。)
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => menu.choose(item)}
            >
              <ReferenceThumb kind={item.kind} id={item.id} />
              <span className="min-w-0 flex-1 truncate text-ui-xs text-foreground">{item.name}</span>
            </button>
          </React.Fragment>
        )}
      </menu.Portal>
    </>
  );
}
