import React from "react";
import type { JSONContent } from "@tiptap/react";

import { ChatComposer, documentText, emptyDocument } from "@/features/agent/ChatComposer";

/**
 * 输入框里正在写的那份草稿,放在面板的渲染状态**之外**(前端架构分析 FA-04)。
 *
 * 此前草稿是面板顶层的 useState:每敲一个字整个面板重渲,一段三百条的对话每个字都要把三百个气泡再算一遍 ——
 * 4× 降频下打字的帧间隔 p95 一秒多,字是一串一串蹦出来的。现在面板只拿着这个盒子、**不订阅它**:
 * 订阅的只有输入框(`DraftComposer`)和看「框里空不空」的发送键(`DraftBlank`);面板自己只在发送、填入、
 * 清空的那一刻 `get` / `set`。
 *
 * 盒子跟着面板活,不跟着输入框:看子代理、切到轨迹时输入框卸掉了,写了一半的话还在这里。
 */
export type ComposerDraft = {
  get: () => JSONContent;
  /** 要发出去的那句话(引用序列化成 `@名字`),和 `get()` 同一份文档。 */
  text: () => string;
  /** 换掉草稿,返回换上的那一份(给要顺手记到别处的调用方,见画布助手的 sessionStorage)。 */
  set: (next: JSONContent | ((current: JSONContent) => JSONContent)) => JSONContent;
  subscribe: (listener: () => void) => () => void;
};

export function createComposerDraft(initial: JSONContent = emptyDocument): ComposerDraft {
  let document = initial;
  let text = documentText(initial);
  const listeners = new Set<() => void>();
  return {
    get: () => document,
    text: () => text,
    set: (next) => {
      const value = typeof next === "function" ? next(document) : next;
      if (value === document) return value;
      document = value;
      text = documentText(value);
      for (const listener of [...listeners]) listener();
      return value;
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

/** 面板持有的那一个盒子:整个面板生命周期里是同一个对象。 */
export function useComposerDraft(initial?: () => JSONContent): ComposerDraft {
  const [draft] = React.useState(() => createComposerDraft(initial?.()));
  return draft;
}

/** 输入框本身 —— 订阅草稿的两处之一。值从盒子里读;改动默认写回盒子,要顺手记到别处的传 `onChange`。 */
export function DraftComposer({
  draft,
  onChange = draft.set,
  ...props
}: Omit<React.ComponentProps<typeof ChatComposer>, "value" | "onChange"> & {
  draft: ComposerDraft;
  onChange?: (next: JSONContent) => void;
}) {
  const value = React.useSyncExternalStore(draft.subscribe, draft.get);
  return <ChatComposer {...props} value={value} onChange={onChange} />;
}

/** 「框里一个字都没有」—— 发送键的可用与否、停止键要不要出现都只看这个。只在空 / 不空翻转时重渲。 */
export function DraftBlank({ draft, children }: { draft: ComposerDraft; children: (blank: boolean) => React.ReactNode }) {
  const blank = React.useSyncExternalStore(draft.subscribe, () => !draft.text().trim());
  return <>{children(blank)}</>;
}
