/**
 * 截屏这一半的纯判断:主进程原因码、框选几何、截图的素材名。
 */
import { describe, expect, it } from "vitest";

import { captureName, frameDisplaySize, pageToolErrorCode, selectionFraction } from "./pageActions";

it("认得主进程拒绝时带的原因码,别的错误不乱认", () => {
  expect(pageToolErrorCode(new Error("Error invoking remote method 'pageTools:capture': PageToolError: page-tools: full_page_unavailable"))).toBe("full_page_unavailable");
  expect(pageToolErrorCode(new Error("network down"))).toBeNull();
});

describe("框选几何", () => {
  const box = { left: 0, top: 56, width: 1000, height: 500 };

  it("窗口坐标换成冻结画面上的比例,反着拖也一样", () => {
    expect(selectionFraction({ x: 600, y: 356 }, { x: 100, y: 106 }, box)).toEqual({ x: 0.1, y: 0.1, width: 0.5, height: 0.5 });
  });

  it("拖出画面的部分夹回来(包括拖到顶栏上)", () => {
    expect(selectionFraction({ x: -50, y: 0 }, { x: 2000, y: 1000 }, box)).toEqual({ x: 0, y: 0, width: 1, height: 1 });
  });

  it("冻结画面整张放进可用区域:高分屏的两倍像素按一半显示,和网页原来一样大", () => {
    expect(frameDisplaySize({ width: 2880, height: 1688 }, { width: 1440, height: 844 })).toEqual({ width: 1440, height: 844 });
  });
});

describe("素材名", () => {
  it("截图:页面标题 · 种类;没有标题用域名", () => {
    expect(captureName({ url: "https://example.com/a", title: "一篇文章" }, "截图")).toBe("一篇文章 · 截图");
    expect(captureName({ url: "https://example.com/a", title: "" }, "截图")).toBe("example.com · 截图");
  });
});
