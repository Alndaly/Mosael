import { useQuery } from "@tanstack/react-query";
import { NodeViewWrapper, ReactNodeViewRenderer, type NodeViewProps } from "@tiptap/react";
import React from "react";

import { noteReferenceQuery } from "@/api/domains/notes";
import { usePreferences } from "@/app/preferences";
import { Hint } from "@/components/ui/tooltip";
import { noteStrings } from "@/features/notes/strings";

/**
 * 引用一篇笔记:**悬停给一块预览**(标题 + 那一版正文的开头),不是原生 `title` 里的名字。
 *
 * 维护者:「文档内部的引用希望支持鼠标 hover 的时候能有预览块 Hint」。名字只够认出是哪一篇;读到一半要
 * 想起"它说的是什么",得点开、翻完、再回来 —— 而引用本来就该在原地回答这件事。
 *
 * ## 只在真的悬停时才问
 *
 * 一篇文档里可能几十个引用,而绝大多数从来没人悬停。渲染时逐个去问就是几十次请求(和
 * `useReferencePreview` 里那条理由一样:不预判)。所以 `enabled` 挂在悬停上,第一次移上去才拉。
 *
 * ## 引的是哪一版就显示哪一版
 *
 * 引用可以钉在某一版上(`noteHref(id, revision)`)。预览走 `/notes/{id}/reference?revision=`,
 * 拿到的是**那一版**的正文 —— 拿当前正文顶替的话,引用的意义(钉住当时那句话)就没了。
 *
 * ## 它不在了就说它不在了
 *
 * 笔记被删掉时接口 404:说明里直说,不留一个看着正常、点开却是空页面的引用。
 */
export function NoteReferenceView({ node, workspaceId }: NodeViewProps & { workspaceId?: string }) {
  const { locale } = usePreferences();
  const s = noteStrings(locale);
  const href = String(node.attrs.href || "");
  const label = String(node.attrs.label || "");
  const { id, revision } = parseNoteHref(href);
  const [hovered, setHovered] = React.useState(false);
  const wanted = Boolean(workspaceId && id && hovered);
  const reference = useQuery({
    ...noteReferenceQuery(workspaceId ?? "", id ?? "", revision ?? undefined),
    enabled: wanted,
  });

  const anchor = (
    <NodeViewWrapper
      as="a"
      href={href}
      data-note-reference=""
      className="note-reference"
      onPointerEnter={() => setHovered(true)}
      onFocus={() => setHovered(true)}
    >
      {`@${label}`}
    </NodeViewWrapper>
  );

  //: 问不出东西的引用(没有工作区、href 不是那个形状)不套说明:一条空说明比没有说明更糟。
  if (!workspaceId || !id) return anchor;
  if (reference.isError) {
    return (
      <Hint label={s.referenceGone.replace("{name}", label)} hint={s.referenceGoneHint}>
        {anchor}
      </Hint>
    );
  }
  //: **一悬停就把说明套上**,内容后到(先把名字摆出来)。等数据回来才套的话,那一次悬停什么也不出 ——
  //: 说明的触发区是这一刻挂上的,指针已经在里面了(Radix 不会再给一次 pointerenter)。
  const found = reference.data;
  //: href 里钉了版本就说一句(`/reference` 拿回来的本来就是那一版)。没钉的是"跟着当前正文走",没什么可说的。
  const pinned = revision ? s.referencePinned.replace("{revision}", String(found?.revision ?? revision)) : "";
  const excerpt = found ? referenceExcerpt(found.markdown) : "";
  return (
    <Hint
      label={found?.title || label}
      hint={[excerpt, pinned].filter(Boolean).join("\n") || null}
      side="top"
    >
      {anchor}
    </Hint>
  );
}

/** 给 `noteReference` 用的节点视图(带上这个编辑器所在的工作区,预览要按工作区问)。 */
export const noteReferenceNodeView = (workspaceId: string) =>
  ReactNodeViewRenderer((props: NodeViewProps) => <NoteReferenceView {...props} workspaceId={workspaceId} />);

/** `#/notes?note=<id>&revision=<n>` 里的两样东西。不是这个形状就返回空 —— 调用方据此什么也不问。 */
export function parseNoteHref(href: string): { id: string | null; revision: number | null } {
  const query = href.includes("?") ? new URLSearchParams(href.slice(href.indexOf("?") + 1)) : null;
  const id = query?.get("note") ?? null;
  const raw = Number(query?.get("revision") ?? "");
  return { id, revision: Number.isFinite(raw) && raw > 0 ? raw : null };
}

/**
 * 预览里的正文:Markdown 的记号去掉、压成几行,够看出是哪一篇、说的是什么。
 *
 * 不做完整的 Markdown 解析(那要拉一个渲染器进来,而且预览块里也不需要排版):剥掉标题、列表、
 * 强调、链接、代码围栏这些**一眼可见的记号**,留下字。太长就截断并留一个省略号。
 */
export function referenceExcerpt(markdown: string, { lines = 6, chars = 240 } = {}): string {
  const plain = markdown
    .replace(/```[\s\S]*?```/g, " ") // 代码块整段略过:预览里它占地方、说明不了什么
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s{0,3}>\s?/gm, "")
    .replace(/^\s{0,3}(?:[-*+]|\d+\.)\s+/gm, "· ")
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/(\*\*|__)(.*?)\1/g, "$2")
    .replace(/(\*|_)(?=\S)(.*?)(?<=\S)\1/g, "$2")
    .replace(/`([^`]+)`/g, "$1");
  const kept = plain
    .split("\n")
    .map((line) => line.trimEnd())
    .filter((line, index, all) => line.trim() || (index > 0 && all[index - 1]?.trim()))
    .slice(0, lines)
    .join("\n")
    .trim();
  return kept.length > chars ? `${kept.slice(0, chars).trimEnd()}…` : kept;
}
