import {
  BookOpen,
  Bot,
  Box,
  Boxes,
  CalendarClock,
  ChartNoAxesCombined,
  FolderOpen,
  LayoutGrid,
  Plug,
  Rocket,
  Scissors,
  Settings,
  ShieldCheck,
  UsersRound,
  Workflow,
  type LucideIcon,
} from "lucide-react";

import type { MessageKey } from "@/app/messages";

/**
 * 页面清单**只有这一份**。
 *
 * 此前侧栏和面包屑各拼各的:侧栏是 `[...SECONDARY_NAV, ADMIN_NAV]`,面包屑是
 * `[...PRIMARY_NAV, ...SECONDARY_NAV]` —— admin 只进了前者,于是 `#/admin` 的面包屑
 * 被 `?? "navEditor"` 兜成了「剪辑」。同一份清单在两处各列一遍,漏掉一项是迟早的事。
 *
 * 侧栏要分组、要按权限过滤,那是**它自己的事**,从这一份里取即可;而"这个页面叫什么"
 * 全应用只有一个答案。
 */
export type StudioView =
  | "statistics"
  | "media"
  | "entities"
  | "notes"
  | "scenes"
  | "editor"
  | "projects"
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
  /** 这一项之前画一条分组线(与 AppShell 现有的那条同款)。 */
  dividerBefore?: boolean;
  keywords: readonly string[];
};

export const NAV_ITEMS: readonly NavItem[] = [
  //: AI Studio 是默认入口;「剪辑」是项目 surface 的入口,没有项目时先落到项目浏览页。
  { view: "ai", labelKey: "navAi", placement: "primary", icon: Bot, keywords: ["ai", "chat", "agent"] },
  { view: "editor", labelKey: "navEditor", placement: "primary", icon: Scissors, keywords: ["editor", "cut", "jianji", "project", "xiangmu"], dividerBefore: true },
  { view: "media", labelKey: "navMedia", placement: "primary", icon: FolderOpen, keywords: ["media", "assets", "sucai"] },
  //: 资产库(ADR 0027):人物、场景、道具。紧挨着「素材」—— 素材是文件,资产是「一个有名字的东西」,参考图是素材。
  { view: "entities", labelKey: "navEntities", placement: "primary", icon: UsersRound, keywords: ["entities", "characters", "zichan", "renwu"] },
  { view: "notes", labelKey: "navNotes", placement: "primary", icon: BookOpen, keywords: ["notes", "biji"] },
  { view: "scenes", labelKey: "navScenes", placement: "primary", icon: Box, keywords: ["scene", "3d", "changjing"] },
  { view: "boards", labelKey: "navBoards", placement: "primary", icon: LayoutGrid, keywords: ["board", "canvas", "huaban"] },
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

/** 可以出现在地址里的页面。项目浏览页是剪辑的空态 surface,不占侧栏一格。 */
export const STUDIO_VIEWS: readonly StudioView[] = [...NAV_ITEMS.map((item) => item.view), "projects"];

/**
 * 不占侧栏一格、但归在某一格下面的页面。
 *
 * 项目浏览页是「剪辑」的空态 surface:从编辑器点面包屑里的「剪辑」回到这里,侧栏点「剪辑」没打开项目时也落到这里。
 * 所以侧栏亮「剪辑」、顶栏也叫「剪辑」。此前两处都没对上:侧栏一格都不亮,顶栏叫「项目」。
 */
const NAV_PARENT: Partial<Record<StudioView, StudioView>> = {
  projects: "editor",
};

/** 这个页面在侧栏里算哪一格(侧栏高亮、面包屑名字都看它)。 */
export function navViewOf(view: StudioView): StudioView {
  return NAV_PARENT[view] ?? view;
}

/** 查不到就是 null。**别兜成首页** —— 那正是 admin 顶着「首页」这个名字的原因。 */
export function navLabelKey(view: StudioView): MessageKey | null {
  return NAV_ITEMS.find((item) => item.view === navViewOf(view))?.labelKey ?? null;
}
