import React from "react";
import { Node, NodeViewWrapper, ReactNodeViewRenderer, mergeAttributes } from "@tiptap/react";

import { assetThumbnailUrl } from "@/api/client";
import { REFERENCE_META, type ReferenceKind } from "@/features/agent/references";
import { useReferencePreview } from "@/features/agent/useReferencePreview";
import { cn } from "@/lib/utils";

/**
 * 正文里的引用胶囊 —— 素材 / 笔记 / 画板 / 工作流**共用这一个节点**,`kind` 是它的属性。
 *
 * `atom: true` 是关键:没有它光标能走进标签内部,退格会咬掉半截名字,留下一个说不清指向谁的
 * 残骸(画布那边的 assetRef 也是为这个)。
 *
 * `renderText` 序列化成 **`@名字`**:`editor.getText()` 拿到的就是发给模型的那句话 ——
 * 「把 @运镜练习 的第三个镜头改长一点」读起来是人话。id 不进正文,它另收进 references
 * (名字会重、会改、会带空格,拿它当标识迟早出事;而 32 位十六进制塞进句子会把句子挤没)。
 */
export const REFERENCE_NODE = "agentRef";

/** 编辑器里的那颗胶囊。点它 = 点开看看(和气泡里一样)。 */
function EditorChip({ node }: { node: { attrs: Record<string, unknown> } }) {
  const open = useReferencePreview();
  const kind = String(node.attrs.kind) as ReferenceKind;
  const id = String(node.attrs.refId);
  const name = String(node.attrs.name ?? "");
  return (
    <NodeViewWrapper as="span" data-agent-ref="">
      <ReferenceBadge kind={kind} id={id} name={name} onOpen={() => void open({ kind, id, name })} />
    </NodeViewWrapper>
  );
}

export const ReferenceChip = Node.create({
  name: REFERENCE_NODE,
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  addAttributes: () => ({ kind: { default: "asset" }, refId: { default: "" }, name: { default: "" } }),
  parseHTML: () => [{ tag: "span[data-agent-ref]" }],
  renderHTML: ({ HTMLAttributes }: { HTMLAttributes: Record<string, unknown> }) => [
    "span",
    mergeAttributes(HTMLAttributes, { "data-agent-ref": "" }),
  ],
  renderText: ({ node }: { node: { attrs: Record<string, unknown> } }) => `@${String(node.attrs.name ?? "")}`,
  addNodeView: () => ReactNodeViewRenderer(EditorChip),
});

/**
 * 菜单行左边那个方块。**尺寸和画布那份提示词框一致**(h-8 w-10):素材给缩略图,
 * 其余给图标 —— 素材是用样子认的,笔记和工作流是用名字认的。
 */
export function ReferenceThumb({ kind, id }: { kind: ReferenceKind; id: string }) {
  const Icon = REFERENCE_META[kind]?.icon ?? REFERENCE_META.asset.icon;
  if (kind === "asset") {
    return <img src={assetThumbnailUrl(id)} alt="" className="h-8 w-10 shrink-0 rounded bg-control object-cover" />;
  }
  return (
    <span className="grid h-8 w-10 shrink-0 place-items-center rounded bg-control text-muted-foreground">
      <Icon size={16} aria-hidden />
    </span>
  );
}

/**
 * 胶囊本身。**输入框里和发出去之后用同一个** —— 两处各画一份的话,同一个引用在输入时和
 * 气泡里长得不一样,而用户刚刚才亲手把它放进去。
 */
export function ReferenceBadge({
  kind,
  id,
  name,
  className,
  onOpen,
}: {
  kind: ReferenceKind;
  id: string;
  name: string;
  className?: string;
  /** 点开看看。输入框里和气泡里都给 —— 同一个东西点起来不该有两种结果。 */
  onOpen?: () => void;
}) {
  const Icon = REFERENCE_META[kind]?.icon ?? REFERENCE_META.asset.icon;
  const Tag = onOpen ? "button" : "span";
  return (
    <Tag
      {...(onOpen
        ? {
            type: "button" as const,
            //: 在编辑器里,mousedown 会把光标挪进原子节点、也会抢焦点 —— 拦掉,
            //: 让 click 干干净净地跑到"点开看看"。
            onMouseDown: (event: React.MouseEvent) => event.preventDefault(),
            onClick: (event: React.MouseEvent) => {
              event.preventDefault();
              event.stopPropagation();
              onOpen();
            },
          }
        : {})}
      data-agent-ref-kind={kind}
      data-agent-ref-id={id}
      title={name}
      className={cn(
        "inline-flex max-w-[200px] items-center gap-1 rounded-md bg-secondary px-1 py-0.5 align-baseline text-ui-2xs text-foreground",
        onOpen && "cursor-pointer hover:bg-secondary/70",
        className,
      )}
    >
      {/* 素材给缩略图,其余给图标 —— 素材是用样子认的,笔记和工作流是用名字认的。 */}
      {kind === "asset" ? (
        <img src={assetThumbnailUrl(id)} alt="" className="h-3.5 w-3.5 shrink-0 rounded-[3px] object-cover" />
      ) : (
        <Icon size={11} className="shrink-0 text-muted-foreground" />
      )}
      <span className="truncate">{name}</span>
    </Tag>
  );
}
