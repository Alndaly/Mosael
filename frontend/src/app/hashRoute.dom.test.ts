/** @vitest-environment jsdom */
import { afterEach, expect, it } from "vitest";

import { readHash, writeHash } from "@/app/hashRoute";

afterEach(() => {
  window.history.replaceState(null, "", "#/");
});

it("页面自己的参数留给那一页去读:AI Studio 的 ?tab=…&session=… 不在启动时被抹掉(页面按需加载,还没挂上)", () => {
  window.history.replaceState(null, "", "#/ai?tab=create&session=s1");
  expect(readHash().view).toBe("ai");
  writeHash("ai", null);
  expect(window.location.hash).toBe("#/ai?tab=create&session=s1");
});

it("别的页照旧写成规范的样子:项目参数是 ?p=,不认识的参数去掉", () => {
  window.history.replaceState(null, "", "#/editor?junk=1");
  writeHash("editor", "p1");
  expect(window.location.hash).toBe("#/editor?p=p1");
  window.history.replaceState(null, "", "#/media?x=1");
  writeHash("media", null);
  expect(window.location.hash).toBe("#/media");
});
