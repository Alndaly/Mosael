/**
 * 会话里多个页面的账本:先后次序、当前页、关掉之后落到哪、按什么找到某一页、上限。
 */
import { describe, expect, it } from "vitest";

import { MAX_PAGES, PageList } from "./pageList";

const pages: Record<string, { title: string; url: string }> = {
  a: { title: "首页 - 示例", url: "https://example.com/" },
  b: { title: "Google 账号登录", url: "https://accounts.google.com/signin" },
  c: { title: "创作中心", url: "https://creator.example.com/upload" },
};
const describePage = (id: string) => pages[id];

function three() {
  const list = new PageList<string>();
  list.add("a", "a", { activate: true });
  list.add("b", "b", { activate: true, after: "a" });
  list.add("c", "c", { activate: false });
  return list;
}

describe("会话里的页面列表", () => {
  it("新开的页面跟在开它的那一页后面;后台打开的不切过去", () => {
    const list = new PageList<string>();
    list.add("a", "a", { activate: true });
    list.add("c", "c", { activate: true });
    list.add("b", "b", { activate: true, after: "a" });
    expect(list.list().map((one) => one.id)).toEqual(["a", "b", "c"]);
    expect(list.current()?.id).toBe("b");
    list.add("d", "d", { activate: false });
    expect(list.current()?.id).toBe("b");
    expect(list.currentIndex()).toBe(2);
  });

  it("关掉当前页落到它上面那一页(关掉弹出来的授权页,回到开它的那一页)", () => {
    const list = three();
    expect(list.current()?.id).toBe("b");
    expect(list.remove("b")).toBe("a");
    expect(list.current()?.id).toBe("a");
  });

  it("关掉的是第一页且是当前页:落到新的第一页;关掉别的页当前页不变;全关了是 null", () => {
    const list = three();
    list.setCurrent("a");
    expect(list.remove("a")).toBe("b");
    expect(list.remove("c")).toBe("b");
    expect(list.remove("b")).toBeNull();
    expect(list.size).toBe(0);
  });

  it("拖动重排:给的次序要和现有的一一对上,否则不认", () => {
    const list = three();
    expect(list.reorder(["c", "a", "b"])).toBe(true);
    expect(list.list().map((one) => one.id)).toEqual(["c", "a", "b"]);
    expect(list.reorder(["c", "a"])).toBe(false);
    expect(list.reorder(["c", "a", "a"])).toBe(false);
    expect(list.reorder(["c", "a", "x"])).toBe(false);
    expect(list.current()?.id).toBe("b"); // 重排不换当前页
  });

  it("按第几个(从 1 起)、标题含、网址含找一页,不分大小写;找不到是 null", () => {
    const list = three();
    expect(list.find({ index: 1 }, describePage)).toBe("a");
    expect(list.find({ index: 3 }, describePage)).toBe("c");
    expect(list.find({ index: 4 }, describePage)).toBeNull();
    expect(list.find({ title: "google" }, describePage)).toBe("b");
    expect(list.find({ url: "CREATOR.example" }, describePage)).toBe("c");
    expect(list.find({ title: "不存在" }, describePage)).toBeNull();
  });

  it("最多开 MAX_PAGES 个,满了不再加", () => {
    const list = new PageList<number>();
    for (let i = 0; i < MAX_PAGES; i += 1) expect(list.add(`p${i}`, i, { activate: true })).toBe(true);
    expect(list.full).toBe(true);
    expect(list.add("one-more", 99, { activate: true })).toBe(false);
    expect(list.size).toBe(MAX_PAGES);
    expect(list.current()?.id).toBe(`p${MAX_PAGES - 1}`);
  });
});
