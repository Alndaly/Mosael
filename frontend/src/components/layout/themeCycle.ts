import { MonitorCog, Moon, Sun, type LucideIcon } from "lucide-react";

import type { MessageKey } from "@/app/messages";
import type { Theme } from "@/app/preferencesContext";

/**
 * 三档主题的顺序、名字和图标。顶栏按钮、⌘K 里那一项、设置 → 外观的分段按钮都读这里,
 * 同一档在三处是同一个图标、同一个名字。
 *
 * 顺序也是「切换主题」按一下去哪:浅 → 深 → 跟随系统 → 浅。此前面板里只在深浅之间互切,
 * 于是同一个动作在两处走两条路:从面板切过的人再也回不到「跟随系统」,而顶栏按一下又会跳进去。
 */
export const THEMES: readonly Theme[] = ["light", "dark", "system"];

export function nextTheme(theme: Theme): Theme {
  return THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
}

export const THEME_LABEL_KEYS: Record<Theme, MessageKey> = {
  light: "themeLight",
  dark: "themeDark",
  system: "themeSystem",
};

export const THEME_ICONS: Record<Theme, LucideIcon> = {
  light: Sun,
  dark: Moon,
  system: MonitorCog,
};
