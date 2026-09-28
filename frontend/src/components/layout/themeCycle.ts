import type { MessageKey } from "@/app/messages";
import type { usePreferences } from "@/app/preferences";

type Theme = ReturnType<typeof usePreferences>["theme"];

/**
 * 「切换主题」按一下去哪:浅 → 深 → 跟随系统 → 浅。
 *
 * 顶栏的按钮和 ⌘K 里那一项共用它。此前面板里只在深浅之间互切,于是同一个动作在两处走两条路:
 * 从面板切过的人再也回不到「跟随系统」,而顶栏按一下又会跳进去。
 */
export function nextTheme(theme: Theme): Theme {
  return theme === "light" ? "dark" : theme === "dark" ? "system" : "light";
}

export const THEME_LABEL_KEYS: Record<Theme, MessageKey> = {
  light: "themeLight",
  dark: "themeDark",
  system: "themeSystem",
};
