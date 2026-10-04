// 工作流「切换页面」节点(以及智能体的 browser_page):在自动化会话的几个页面之间切换、关掉当前页。
//
// 新窗口(target=_blank、window.open)会进会话的页面列表并自动切过去(见 accountViews.openWindow),所以
// 「点了一个在新窗口打开的链接,下一步就在新页面上接着做」不需要这个节点;要回到原来那一页、或者跳到
// 某个特定的页面、或者看完关掉,才用它。
import type { AccountViewManager } from "./accountViews";
import type { ActionOutcome } from "./browserActions";
import type { PageMatch } from "./pageList";
import { t } from "../i18n.cjs";

export const PAGE_OPERATIONS = ["switch", "close", "list"] as const;
export const PAGE_MATCHES = ["index", "title", "url"] as const;

/** 动作结果里交回的那一份:当前是第几页、它的标题和网址、一共几页、每一页是什么。 */
export interface PageResult {
  index: number;
  title: string;
  url: string;
  count: number;
  pages: Array<{ index: number; title: string; url: string; current: boolean }>;
}

const brief = (v: string, max = 80): string => (v.length <= max ? v : `${v.slice(0, max - 1)}…`);

/**
 * 「找哪一页」:按第几个(从 1 起)/ 标题含 / 网址含。「截图」节点截某一页时也用这一套(同样的报错)。
 * 交回匹配条件和给人看的那半句(「第 2 个页面」「标题含「…」的页面」)。
 */
export function pageMatch(byArg: unknown, valueArg: unknown): { match: PageMatch; what: string } {
  const by = (PAGE_MATCHES as readonly string[]).includes(String(byArg)) ? String(byArg) : "index";
  const value = String(valueArg ?? "").trim();
  if (!value) throw new Error(t("browserErr_pageNeedsTarget"));
  if (by === "index") {
    const index = Number(value);
    if (!Number.isInteger(index) || index < 1) throw new Error(t("browserErr_pageBadIndex", { value: brief(value, 20) }));
    return { match: { index }, what: t("browserErr_pageWhatIndex", { index }) };
  }
  return by === "title"
    ? { match: { title: value }, what: t("browserErr_pageWhatTitle", { value: brief(value) }) }
    : { match: { url: value }, what: t("browserErr_pageWhatUrl", { value: brief(value) }) };
}

export function pageForAction(views: AccountViewManager, sessionId: string, args: Record<string, unknown>): ActionOutcome {
  const operation = (PAGE_OPERATIONS as readonly string[]).includes(String(args.operation)) ? String(args.operation) : "switch";
  if (operation === "switch") {
    const { match, what } = pageMatch(args.by, args.value);
    const id = views.findPage(sessionId, match);
    if (!id) throw new Error(t("browserErr_pageNotFound", { what, count: views.pagesOf(sessionId).length }));
    views.switchPage(sessionId, id);
  } else if (operation === "close") {
    const id = views.currentPageId(sessionId);
    if (!id || !views.closePage(sessionId, id)) throw new Error(t("browserErr_pageLastOne"));
  }
  const pages = views.pagesOf(sessionId);
  const current = Math.max(0, pages.findIndex((one) => one.current));
  const value: PageResult = {
    index: current + 1,
    title: pages[current]?.title ?? "",
    url: pages[current]?.url ?? "",
    count: pages.length,
    pages: pages.map((one, index) => ({ index: index + 1, title: one.title, url: one.url, current: one.current })),
  };
  return { value, lastUrl: value.url };
}
