import React from "react";
import { Boxes } from "lucide-react";

import type { MessageKey } from "@/app/messages";
import { NAV_ITEMS, navLabelKey, type StudioView } from "@/components/layout/navLabels";

/**
 * 侧栏快捷方式:一个动作 + 一个图标。值是本机偏好,不进后端 —— 它描述的是"这个人怎么用这扇门",
 * 和主题、页签密度一样只活在这台机器上。
 *
 * 存两种动作:
 * - `view`:跳到某个工作区页面;
 * - `comfyui-workbench`:直接打开某台 ComfyUI 的工作台(桌面版);网页版退化成新标签页。
 */
export type SidebarShortcut =
  | { id: string; kind: "view"; view: StudioView }
  | { id: string; kind: "comfyui-workbench"; instanceId: string; instanceName: string; url: string };

const STORAGE_KEY = "mosael:sidebar-shortcuts";

function read(): SidebarShortcut[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isShortcut).filter((one, index, all) => all.findIndex((x) => x.id === one.id) === index);
  } catch {
    return [];
  }
}

function isShortcut(value: unknown): value is SidebarShortcut {
  if (!value || typeof value !== "object") return false;
  const one = value as Record<string, unknown>;
  if (typeof one.id !== "string") return false;
  if (one.kind === "view") return typeof one.view === "string";
  if (one.kind === "comfyui-workbench") {
    return typeof one.instanceId === "string" && typeof one.instanceName === "string" && typeof one.url === "string";
  }
  return false;
}

let shortcuts = typeof localStorage === "undefined" ? [] : read();
const listeners = new Set<() => void>();

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

export function setSidebarShortcuts(next: readonly SidebarShortcut[]) {
  shortcuts = next.slice();
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(shortcuts));
  } catch {
    // 隐私模式/无 storage:退化为这次打开有效。
  }
  listeners.forEach((listener) => listener());
}

export function useSidebarShortcuts(): readonly SidebarShortcut[] {
  return React.useSyncExternalStore(subscribe, () => shortcuts, () => shortcuts);
}

export function shortcutLabel(shortcut: SidebarShortcut, t: (key: MessageKey) => string): string {
  if (shortcut.kind === "comfyui-workbench") return `${t("sidebarShortcutsComfyWorkbench")} · ${shortcut.instanceName}`;
  const key = navLabelKey(shortcut.view);
  return key ? t(key) : shortcut.view;
}

export function shortcutIdForView(view: StudioView): string {
  return `view:${view}`;
}

export function shortcutForView(view: StudioView): SidebarShortcut {
  return { id: shortcutIdForView(view), kind: "view", view };
}

export function shortcutIdForComfy(instanceId: string): string {
  return `comfyui:${instanceId}`;
}

export function shortcutForComfy(instanceId: string, instanceName: string, url: string): SidebarShortcut {
  return { id: shortcutIdForComfy(instanceId), kind: "comfyui-workbench", instanceId, instanceName, url };
}

export function shortcutIcon(shortcut: SidebarShortcut): React.ComponentType<{ size?: number }> {
  if (shortcut.kind === "comfyui-workbench") return Boxes;
  return NAV_ITEMS.find((item) => item.view === shortcut.view)?.icon ?? Boxes;
}
