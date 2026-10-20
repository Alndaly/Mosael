"use client";

import * as React from "react";

export type ToastItem = {
  id: string;
  title: string;
  description?: string;
};

/**
 * toast 的队列。
 *
 * 一个模块级小 store:表单成功的那一刻 `toast({ title })`,由挂在根布局的 `<Toaster />` 画出来。
 * **文案不在这里拼** —— 调用方传的是已经按当前语言从 `messages.ts` 取好的字符串。
 */
const TOAST_LIMIT = 3;
// 退场动画播完再把这条从队列里摘掉;Radix 自己的 5 秒没有动(见 toast.tsx 的 Provider 默认值)。
const TOAST_REMOVE_DELAY = 400;

const EMPTY: ReadonlyArray<ToastItem> = [];
let toasts: ReadonlyArray<ToastItem> = EMPTY;
const listeners = new Set<() => void>();
const removalTimers = new Map<string, ReturnType<typeof setTimeout>>();
let sequence = 0;

function notify() {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot() {
  return toasts;
}

function getServerSnapshot() {
  return EMPTY;
}

/** 排一条 toast。返回的 id 给需要主动关掉它的调用方。 */
export function toast({ title, description }: { title: string; description?: string }) {
  sequence += 1;
  const id = String(sequence);
  toasts = [{ id, title, description }, ...toasts].slice(0, TOAST_LIMIT);
  notify();
  return id;
}

/** 关掉一条:先让 Radix 播完退场动画,再把它从队列里摘掉。 */
export function dismissToast(id: string) {
  if (removalTimers.has(id)) return;
  removalTimers.set(
    id,
    setTimeout(() => {
      removalTimers.delete(id);
      toasts = toasts.filter((item) => item.id !== id);
      notify();
    }, TOAST_REMOVE_DELAY),
  );
}

export function useToast() {
  const current = React.useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return { toasts: current, toast, dismiss: dismissToast };
}
