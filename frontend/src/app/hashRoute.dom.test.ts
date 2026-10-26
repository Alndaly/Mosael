/** @vitest-environment jsdom */
import { afterEach, expect, it } from "vitest";

import { projectAfterHashChange, readHash, writeHash } from "@/app/hashRoute";
import type { StudioView } from "@/components/layout/AppShell";

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

it("侧栏换页不丢当前项目;只有回到剪辑且不带 p 才清空", () => {
  const next = (view: StudioView, projectId: string | null = null) => ({ view, projectId });
  expect(projectAfterHashChange("p1", next("scenes"))).toBe("p1");
  expect(projectAfterHashChange("p1", next("notes"))).toBe("p1");
  expect(projectAfterHashChange("p1", next("editor"))).toBeNull();
  expect(projectAfterHashChange("p1", next("editor", "p2"))).toBe("p2");
});

it("写回地址时项目参数和页面自己的参数一起保留,刷新不丢", () => {
  window.history.replaceState(null, "", "#/notes?note=n1");
  writeHash("notes", "p1");
  const notes = new URLSearchParams(window.location.hash.split("?")[1]);
  expect(notes.get("note")).toBe("n1");
  expect(notes.get("p")).toBe("p1");

  window.history.replaceState(null, "", "#/editor?p=p1&s=seq-2");
  writeHash("editor", "p1");
  const editor = new URLSearchParams(window.location.hash.split("?")[1]);
  expect(editor.get("p")).toBe("p1");
  expect(editor.get("s")).toBe("seq-2");
});

it("不认识的页面落到剪辑的项目浏览器(不留旧页面兼容分支)", () => {
  window.history.replaceState(null, "", "#/home");
  expect(readHash()).toEqual({ view: "editor", projectId: null });
  writeHash("editor", null);
  expect(window.location.hash).toBe("#/editor");

  window.history.replaceState(null, "", "#/");
  expect(readHash()).toEqual({ view: "editor", projectId: null });

  window.history.replaceState(null, "", "#/editor?p=p1");
  expect(readHash()).toEqual({ view: "editor", projectId: "p1" });
});
