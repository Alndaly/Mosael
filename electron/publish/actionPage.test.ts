/**
 * 「切换页面」节点在执行器这一侧:按第几个 / 标题 / 网址切过去、关掉当前页、找不到或只剩一页时说人话、
 * 交回当前是哪一页和全部页面。会话的页面账本用真的 PageList 搭一个小假货(真管理器在 accountViewsPanels 里测)。
 */
import { describe, expect, it } from "vitest";

import { pageForAction } from "./actionPage";
import { PageList } from "./pageList";

function fakeViews(pages: Array<{ title: string; url: string }>) {
  const list = new PageList<{ title: string; url: string }>();
  pages.forEach((page, index) => list.add(String(index + 1), page, { activate: index === 0 }));
  const closed: string[] = [];
  const views = {
    findPage: (_session: string, match: Parameters<typeof list.find>[0]) => list.find(match, (page) => page),
    switchPage: (_session: string, id: string) => list.setCurrent(id),
    currentPageId: () => list.current()?.id ?? null,
    closePage: (_session: string, id: string) => {
      if (list.size <= 1) return false;
      closed.push(id);
      list.remove(id);
      return true;
    },
    pagesOf: () => list.list().map(({ id, item }) => ({ id, ...item, favicon: "", current: id === list.current()?.id })),
  };
  return { views: views as never, list, closed };
}

const PAGES = [
  { title: "首页", url: "https://example.com/" },
  { title: "Google 账号登录", url: "https://accounts.google.com/signin" },
  { title: "创作中心", url: "https://creator.example.com/upload" },
];

describe("「切换页面」节点", () => {
  it("按第几个 / 标题 / 网址切过去,交回当前页和全部页面", () => {
    const { views, list } = fakeViews(PAGES);
    let outcome = pageForAction(views, "s1", { operation: "switch", by: "index", value: "3" });
    expect(list.current()?.id).toBe("3");
    expect(outcome.lastUrl).toBe("https://creator.example.com/upload");
    expect(outcome.value).toMatchObject({ index: 3, title: "创作中心", count: 3 });
    outcome = pageForAction(views, "s1", { operation: "switch", by: "title", value: "google" });
    expect((outcome.value as { index: number }).index).toBe(2);
    outcome = pageForAction(views, "s1", { by: "url", value: "example.com/" });
    expect((outcome.value as { pages: Array<{ current: boolean }> }).pages.map((one) => one.current)).toEqual([true, false, false]);
  });

  it("关掉当前页:落到它上面那一页;只剩一页时不关并说清为什么", () => {
    const { views, list, closed } = fakeViews(PAGES.slice(0, 2));
    list.setCurrent("2");
    const outcome = pageForAction(views, "s1", { operation: "close" });
    expect(closed).toEqual(["2"]);
    expect(outcome.value).toMatchObject({ index: 1, count: 1, url: "https://example.com/" });
    expect(() => pageForAction(views, "s1", { operation: "close" })).toThrow(/唯一的页面/);
  });

  it("找不到、没说切到哪一页、第几个不是正整数:都说人话", () => {
    const { views } = fakeViews(PAGES);
    expect(() => pageForAction(views, "s1", { by: "title", value: "不存在" })).toThrow(/标题含「不存在」.*3 个页面/);
    expect(() => pageForAction(views, "s1", { by: "index", value: "9" })).toThrow(/第 9 个页面/);
    expect(() => pageForAction(views, "s1", { by: "index", value: "" })).toThrow(/要切到哪一页/);
    expect(() => pageForAction(views, "s1", { by: "index", value: "1.5" })).toThrow(/正整数/);
  });

  it("只看看有哪些页面(智能体用):不切不关", () => {
    const { views, list } = fakeViews(PAGES);
    const outcome = pageForAction(views, "s1", { operation: "list" });
    expect(list.current()?.id).toBe("1");
    expect((outcome.value as { pages: unknown[] }).pages).toHaveLength(3);
  });
});
