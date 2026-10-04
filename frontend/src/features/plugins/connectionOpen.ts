import React from "react";

/**
 * 插件页上每个连接**展开还是收起**,按连接记在本机(浏览器存储)。
 *
 * 默认:一个插件只有一个连接时展开(没什么要找的);有好几个时收起,一眼看全(用户原话:「插件页面我希望每一个连接
 * 可以收起 这样方便查看」);刚新建的那个展开(`setOpen(id, true)`,调用方在建好时说)。用户点过的照他点的记。
 *
 * 存储只是记个方便:隐私模式、被禁用、存进去的不是 JSON —— 读写都包着,出错就照默认摆,不影响页面。
 */

export const CONNECTIONS_OPEN_KEY = "mosael.plugins.connectionsOpen";

export function readOpenConnections(): Record<string, boolean> {
  try {
    const raw = window.localStorage.getItem(CONNECTIONS_OPEN_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).filter((entry): entry is [string, boolean] => typeof entry[1] === "boolean"),
    );
  } catch {
    return {};
  }
}

function writeOpenConnections(value: Record<string, boolean>): void {
  try {
    window.localStorage.setItem(CONNECTIONS_OPEN_KEY, JSON.stringify(value));
  } catch {
    // 存不下就只在这一次打开里记着
  }
}

export function useConnectionOpen(instanceIds: string[]): {
  isOpen: (id: string) => boolean;
  setOpen: (id: string, open: boolean) => void;
  setAll: (open: boolean) => void;
  anyOpen: boolean;
} {
  const [stored, setStored] = React.useState<Record<string, boolean>>(readOpenConnections);
  const fallback = instanceIds.length === 1;
  const isOpen = React.useCallback((id: string) => stored[id] ?? fallback, [stored, fallback]);
  const update = React.useCallback((next: Record<string, boolean>) => {
    setStored((current) => {
      const merged = { ...current, ...next };
      writeOpenConnections(merged);
      return merged;
    });
  }, []);
  const setOpen = React.useCallback((id: string, open: boolean) => update({ [id]: open }), [update]);
  const setAll = React.useCallback(
    (open: boolean) => update(Object.fromEntries(instanceIds.map((id) => [id, open]))),
    [instanceIds, update],
  );
  return { isOpen, setOpen, setAll, anyOpen: instanceIds.some((id) => isOpen(id)) };
}
