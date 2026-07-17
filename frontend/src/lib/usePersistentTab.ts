import React from "react";

/**
 * 页面级 tab 状态,持久化到 localStorage:刷新后仍停在对应 tab。
 * key 需全局唯一(如 "publish" / "ai-studio")。allowed 用于校验旧值,
 * 避免 storage 里的陈旧/非法值把视图带到不存在的分支。
 */
export function usePersistentTab<T extends string>(key: string, initial: T, allowed: readonly T[]): [T, (value: T) => void] {
  const storageKey = `mibu:tab:${key}`;
  const [tab, setTab] = React.useState<T>(() => {
    try {
      const stored = localStorage.getItem(storageKey) as T | null;
      return stored && allowed.includes(stored) ? stored : initial;
    } catch {
      return initial;
    }
  });
  const set = React.useCallback(
    (value: T) => {
      setTab(value);
      try {
        localStorage.setItem(storageKey, value);
      } catch {
        // 隐私模式 / 无 storage:退化为纯内存状态即可。
      }
    },
    [storageKey],
  );
  return [tab, set];
}
