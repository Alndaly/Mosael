import React from "react";

/**
 * 页面级 tab 状态,持久化到 localStorage:刷新后仍停在对应 tab。
 * key 需全局唯一(如 "publish" / "ai-studio")。allowed 用于校验旧值,
 * 避免 storage 里的陈旧/非法值把视图带到不存在的分支。
 */
export function usePersistentTab<T extends string>(key: string, initial: T, allowed: readonly T[]): [T, (value: T) => void] {
  const storageKey = `openstudio:tab:${key}`;
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


/**
 * 会**活过导航**的「选中了哪一个」—— 工作流、插件、发布记录、定时任务都是这个形状。
 *
 * 和 `usePersistentTab` 的区别在于合法值是**动态的**:tab 的候选写死在代码里,而选中的那一项来自
 * 服务端,而且会被删掉。所以存下来的 id 每次都要对着当前列表验一遍,验不过就当没选过。
 *
 * **列表还没加载出来时不清空**(`ids` 为空 = 还不知道有哪些,不是"一个都没有")。少了这一条,
 * 首屏那一瞬间就会把存着的选择判成非法然后抹掉 —— 表现是"偶尔记得住,偶尔记不住"。
 */
export function usePersistentSelection(
  key: string,
  ids: readonly string[],
): [string | null, (value: string | null) => void] {
  const storageKey = `openstudio:selected:${key}`;
  const [selected, setSelected] = React.useState<string | null>(() => {
    try {
      return localStorage.getItem(storageKey);
    } catch {
      return null;
    }
  });

  const set = React.useCallback(
    (value: string | null) => {
      setSelected(value);
      try {
        if (value === null) localStorage.removeItem(storageKey);
        else localStorage.setItem(storageKey, value);
      } catch {
        // 隐私模式 / 无 storage:退化为纯内存状态即可。
      }
    },
    [storageKey],
  );

  const valid = selected !== null && (ids.length === 0 || ids.includes(selected));
  return [valid ? selected : null, set];
}
