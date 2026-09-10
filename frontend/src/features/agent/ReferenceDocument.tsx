import React from "react";
import type { JSONContent } from "@tiptap/react";

import { ReferenceBadge } from "@/features/agent/ReferenceChip";
import { useReferencePreview } from "@/features/agent/useReferencePreview";
import { REFERENCE_NODE } from "@/features/agent/ReferenceChip";
import type { ReferenceKind } from "@/features/agent/references";

/**
 * 把编辑器存下来的那份文档画成气泡里的正文。
 *
 * **不重新起一个 tiptap 实例。** 只读渲染要的是"照着这棵树画出来",而一个编辑器实例带着
 * 输入法、选区、插件和一整套事件 —— 一屏几十条消息各挂一个,代价全花在没人会去编辑的东西上。
 * 这棵树的形状是我们自己定的(段落 / 文本 / 引用),遍历它比装一个编辑器诚实。
 *
 * 认不出来的节点**照它的文本渲染**,不丢内容:文档格式以后长出新节点时,老版本至少还能
 * 把字读出来,而不是空一块。
 */
export function ReferenceDocument({ document }: { document: JSONContent }) {
  const open = useReferencePreview();
  return <div className="whitespace-pre-wrap">{(document.content ?? []).map((node, at) => renderBlock(node, at, open))}</div>;
}

type Open = (reference: { kind: ReferenceKind; id: string; name: string }) => void;

function renderBlock(node: JSONContent, index: number, open: Open): React.ReactNode {
  if (node.type === "paragraph") {
    return (
      <p key={index} className="m-0">
        {(node.content ?? []).map((child, at) => renderInline(child, at, open))}
        {/* 空段落要占一行 —— 用户敲的空行是他排的版。 */}
        {(node.content ?? []).length === 0 && <br />}
      </p>
    );
  }
  return <React.Fragment key={index}>{(node.content ?? []).map((child, at) => renderInline(child, at, open))}</React.Fragment>;
}

function renderInline(node: JSONContent, index: number, open: Open): React.ReactNode {
  if (node.type === REFERENCE_NODE) {
    const attrs = (node.attrs ?? {}) as { kind?: string; refId?: string; name?: string };
    const reference = {
      kind: (attrs.kind ?? "asset") as ReferenceKind,
      id: attrs.refId ?? "",
      name: attrs.name ?? "",
    };
    return <ReferenceBadge key={index} {...reference} className="mx-0.5" onOpen={() => open(reference)} />;
  }
  if (node.type === "hardBreak") return <br key={index} />;
  return <React.Fragment key={index}>{node.text ?? ""}</React.Fragment>;
}
