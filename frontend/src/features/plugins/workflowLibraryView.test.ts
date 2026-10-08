import { describe, expect, it } from "vitest";

import type { WorkflowFile } from "@/api/client";
import {
  ALL_WORKFLOWS,
  conflictOf,
  filterWorkflows,
  filesIn,
  folderOfView,
  folderPathFrom,
  folderTree,
  folderView,
  freeFolderPath,
  inView,
  notEmptyOf,
  validFolderPath,
} from "./workflowLibraryView";

/**
 * 工作流库左栏的文件夹树和改文件夹时的几样纯函数(ADR 0035 后续「文件夹」)。
 */

const flow = (path: string) => ({ path, label: path, folder: path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "" }) as WorkflowFile;
const failure = (detail: unknown) => Object.assign(new Error("409"), { status: 409, body: JSON.stringify({ detail }) });

describe("文件夹树", () => {
  it("插件报的加上工作流所在的,补齐上级;同一层按名字的自然顺序,数量连同子文件夹", () => {
    const workflows = [flow("a.json"), flow("v/x.json"), flow("v/drafts/y.json"), flow("img 10/z.json"), flow("img 9/z.json")];
    expect(folderTree(["空的", "v/deep/deeper"], workflows)).toEqual([
      { path: "img 9", name: "img 9", depth: 0, count: 1 },
      { path: "img 10", name: "img 10", depth: 0, count: 1 },
      { path: "v", name: "v", depth: 0, count: 2 },
      { path: "v/deep", name: "deep", depth: 1, count: 0 },
      { path: "v/deep/deeper", name: "deeper", depth: 2, count: 0 },
      { path: "v/drafts", name: "drafts", depth: 1, count: 1 },
      { path: "空的", name: "空的", depth: 0, count: 0 },
    ]);
  });

  it("选一个文件夹:它和它下面的;名字只是前缀相同的别的文件夹不算", () => {
    const workflows = [flow("v/x.json"), flow("v/草稿/y.json"), flow("video/z.json")];
    expect(inView(workflows, folderView("v")).map((one) => one.path)).toEqual(["v/x.json", "v/草稿/y.json"]);
    expect(inView(workflows, ALL_WORKFLOWS)).toHaveLength(3);
    expect(folderOfView(folderView("__all__")), "叫 __all__ 的文件夹也和「全部」分得开").toBe("__all__");
    expect(folderOfView(ALL_WORKFLOWS)).toBeNull();
    expect(filesIn("v", ["v/x.json", "v/pack.zip", "video/z.json"])).toBe(2);
  });
});

describe("文件夹名", () => {
  it("输入框里的字:去掉开头的 workflows/ 和末尾的 /;和工作流路径同一套分段规则,不以 .json 结尾", () => {
    expect(folderPathFrom("  workflows/人像/草稿/ ")).toBe("人像/草稿");
    for (const good of ["人像", "a/b c", "v (1)"]) expect(validFolderPath(good), good).toBe(true);
    for (const bad of ["", "../x", "a//b", ".hidden", "a/.b", "a:b", "x.json", "a /b", "a\\b"]) expect(validFolderPath(bad), bad).toBe(false);
  });

  it("不撞名的建议:不分大小写比(那台机器可能是 Windows)", () => {
    expect(freeFolderPath("Video", ["video", "video (1)"])).toBe("Video (2)");
    expect(freeFolderPath("新的", ["video"])).toBe("新的");
  });

  it("409 分得清:撞名(带建议名)和文件夹不空(带个数)", () => {
    expect(conflictOf(failure({ code: "exists", suggestion: "a (1)" }))).toEqual({ suggestion: "a (1)" });
    expect(conflictOf(failure({ code: "not_empty", count: 2 })), "不空不是撞名").toBeNull();
    expect(conflictOf(failure({ code: "stale", modified: 1 }))).toBeNull();
    expect(notEmptyOf(failure({ code: "not_empty", count: 2 }))).toEqual({ count: 2 });
    expect(notEmptyOf(failure({ code: "exists", suggestion: "" }))).toBeNull();
    expect(notEmptyOf(new Error("x"))).toBeNull();
  });
});

describe("搜索", () => {
  it("每张表单的标题都算(ADR 0045):AI Studio 里看到「快速用krea2生图」「精调」,在库里搜得到是哪张工作流", () => {
    const form = (id: string, title: string) => ({ id, title, description: "", fields: 1, invalid: 0, model: "", tool: "" });
    const formed = {
      ...flow("krea2-text-2-image.json"),
      app: { status: "ok", version: "", upgradable: false, invalid: 0, stray: 0, results: [],
             forms: [form("app", "快速用krea2生图"), form("k3x9a2", "精调")] },
    } as WorkflowFile;
    const other = flow("girl.json");
    expect(filterWorkflows([formed, other], { kind: "all", query: "快速" })).toEqual([formed]);
    expect(filterWorkflows([formed, other], { kind: "all", query: "精调" })).toEqual([formed]);
    expect(filterWorkflows([formed, other], { kind: "all", query: "krea2" })).toEqual([formed]);
  });
});
