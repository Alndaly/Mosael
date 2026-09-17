import {
  BookOpen,
  Bot,
  Box,
  Boxes,
  CalendarClock,
  ChartNoAxesCombined,
  FolderOpen,
  Home,
  LayoutGrid,
  Plug,
  Rocket,
  Scissors,
  Settings,
  ShieldCheck,
  Workflow,
  type LucideIcon,
} from "lucide-react";

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
  | "statistics"
  | "media"
  | "notes"
  | "scenes"
  | "editor"
  | "ai"
  | "publish"
  | "settings"
  | "workflows"
  | "boards"
  | "scheduler"
  | "plugins"
  | "browser-pool"
  | "admin";

/**
 * 一个页面在导航里怎么出现。**只有元数据** —— 渲染哪个组件在 `app/pages.tsx`,那一层才可以
 * import 各个功能模块;这里要被侧栏、面包屑、命令面板共用,不能反过来依赖它们。
 *
 * `placement`:
 *   - primary / secondary — 侧栏上半、下半两组;
 *   - admin — 只对部署管理员出现;
 *   - footer — 侧栏底部单独一格(设置)。此前设置被标成 primary,侧栏渲染时再特判滤掉 ——
 *     声明说它在上面,实际在底下。
 *
 * `keywords` 给命令面板做英文 / 拼音前缀匹配。此前命令面板自己抄了一份页面清单,漏掉了
 * 笔记、3D 场景、画板、管理 —— ⌘K 里根本跳不过去。
 */
export type NavPlacement = "primary" | "secondary" | "admin" | "footer";

export type NavItem = {
  view: StudioView;
  labelKey: MessageKey;
  placement: NavPlacement;
  icon: LucideIcon;
  keywords: readonly string[];
};

export const NAV_ITEMS: readonly NavItem[] = [
  { view: "home", labelKey: "navHome", placement: "primary", icon: Home, keywords: ["home", "shouye"] },
  { view: "media", labelKey: "navMedia", placement: "primary", icon: FolderOpen, keywords: ["media", "assets", "sucai"] },
  { view: "notes", labelKey: "navNotes", placement: "primary", icon: BookOpen, keywords: ["notes", "biji"] },
  { view: "scenes", labelKey: "navScenes", placement: "primary", icon: Box, keywords: ["scene", "3d", "changjing"] },
  { view: "boards", labelKey: "navBoards", placement: "primary", icon: LayoutGrid, keywords: ["board", "canvas", "huaban"] },
  { view: "editor", labelKey: "navEditor", placement: "primary", icon: Scissors, keywords: ["editor", "cut", "jianji"] },
  { view: "ai", labelKey: "navAi", placement: "primary", icon: Bot, keywords: ["ai", "chat", "agent"] },
  { view: "publish", labelKey: "navPublish", placement: "secondary", icon: Rocket, keywords: ["publish", "fabu"] },
  { view: "workflows", labelKey: "navWorkflows", placement: "secondary", icon: Workflow, keywords: ["workflow", "flow", "gongzuoliu"] },
  {
    view: "browser-pool",
    labelKey: "navBrowserPool",
    placement: "secondary",
    icon: Boxes,
    keywords: ["browser", "pool", "account", "liulanqi", "zhanghao"],
  },
  { view: "scheduler", labelKey: "schedulerTitle", placement: "secondary", icon: CalendarClock, keywords: ["schedule", "cron", "dingshi"] },
  { view: "plugins", labelKey: "pluginsTitle", placement: "secondary", icon: Plug, keywords: ["plugins", "chajian"] },
  {
    view: "statistics",
    labelKey: "navStatistics",
    placement: "secondary",
    icon: ChartNoAxesCombined,
    keywords: ["statistics", "analytics", "tongji", "usage"],
  },
  { view: "admin", labelKey: "navAdmin", placement: "admin", icon: ShieldCheck, keywords: ["admin", "guanli"] },
  { view: "settings", labelKey: "navSettings", placement: "footer", icon: Settings, keywords: ["settings", "shezhi"] },
];

export function navItemsAt(placement: NavPlacement): readonly NavItem[] {
  return NAV_ITEMS.filter((item) => item.placement === placement);
}

export const STUDIO_VIEWS: readonly StudioView[] = NAV_ITEMS.map((item) => item.view);

/** 查不到就是 null。**别兜成首页** —— 那正是 admin 顶着「首页」这个名字的原因。 */
export function navLabelKey(view: StudioView): MessageKey | null {
  return NAV_ITEMS.find((item) => item.view === view)?.labelKey ?? null;
}
