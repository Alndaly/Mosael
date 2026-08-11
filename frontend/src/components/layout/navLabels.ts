import type { MessageKey } from "@/app/messages";

/**
 * 页面清单**只有这一份**。
 *
 * 此前侧栏和面包屑各拼各的:侧栏是 `[...SECONDARY_NAV, ADMIN_NAV]`,面包屑是
 * `[...PRIMARY_NAV, ...SECONDARY_NAV]` —— admin 只进了前者,于是 `#/admin` 的面包屑
 * 被 `?? "navHome"` 兜成了「首页」。同一份清单在两处各列一遍,漏掉一项是迟早的事。
 *
 * 侧栏要分组、要按权限过滤,那是**它自己的事**,从这一份里取即可;而"这个页面叫什么"
 * 全应用只有一个答案。
 */
export type StudioView =
  | "home"
  | "media"
  | "editor"
  | "ai"
  | "publish"
  | "settings"
  | "workflows"
  | "scheduler"
  | "plugins"
  | "browser-pool"
  | "admin";

export type NavItem = { view: StudioView; labelKey: MessageKey; group: "primary" | "secondary" | "admin" };

export const NAV_ITEMS: readonly NavItem[] = [
  { view: "home", labelKey: "navHome", group: "primary" },
  { view: "media", labelKey: "navMedia", group: "primary" },
  { view: "editor", labelKey: "navEditor", group: "primary" },
  { view: "ai", labelKey: "navAi", group: "primary" },
  { view: "publish", labelKey: "navPublish", group: "primary" },
  { view: "settings", labelKey: "navSettings", group: "primary" },
  { view: "workflows", labelKey: "navWorkflows", group: "secondary" },
  { view: "browser-pool", labelKey: "navBrowserPool", group: "secondary" },
  { view: "scheduler", labelKey: "schedulerTitle", group: "secondary" },
  { view: "plugins", labelKey: "pluginsTitle", group: "secondary" },
  { view: "admin", labelKey: "navAdmin", group: "admin" },
];

export const STUDIO_VIEWS: readonly StudioView[] = NAV_ITEMS.map((item) => item.view);

/** 查不到就是 null。**别兜成首页** —— 那正是 admin 顶着「首页」这个名字的原因。 */
export function navLabelKey(view: StudioView): MessageKey | null {
  return NAV_ITEMS.find((item) => item.view === view)?.labelKey ?? null;
}
