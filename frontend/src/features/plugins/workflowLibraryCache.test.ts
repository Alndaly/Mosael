/** @vitest-environment jsdom */
import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import type { WorkflowLibrary } from "@/api/client";
import {
  libraryAddFolder,
  libraryMovePath,
  libraryRemoveFolder,
  libraryRenameFolder,
  rebase,
  underPath,
} from "./workflowLibraryCache";

/**
 * 文件夹 / 工作流挪动之后**先就地改手里这一份**的规则(维护者:「创建分组/文件夹后界面上虽然提交了、弹窗也关了,
 * 但左边文件夹还是原先那几个,要过很久或者刷新一下才出现」——那一份是问 ComfyUI 扫一遍回来的,几秒起步)。
 *
 * 规则和服务端做的是同一件事:改 `workflows/` 下的路径。文件夹改名时里面每一个文件的路径跟着变。
 */

const KEY = ["workflow-library", "i1", "w1"] as const;

/** 一份够用的库(字段按 schema 给全;列表那几栏只是读路径,别的照实留空)。 */
type LibraryWorkflow = NonNullable<WorkflowLibrary["workflows"]>[number];
const flow = (path: string, label: string, folder: string): LibraryWorkflow =>
  ({ path, label, folder, kind: "image", problem: "", node_count: 0 });

const data: WorkflowLibrary = {
  workflows: [flow("a.json", "A", ""), flow("组/一.json", "一", "组"), flow("组/子/二.json", "二", "组/子")],
  folders: ["组", "组/子", "别的"],
  //: 「别的文件」那一栏只有路径和读不出来的原因(没有 label)。
  others: [{ path: "组/说明.txt", reason: "" }],
  trash: [{ path: "组/.trash/三.json", original: "组/三.json", label: "三" }],
};

function withData() {
  const qc = new QueryClient();
  qc.setQueryData(KEY, structuredClone(data));
  return qc;
}

const read = (qc: QueryClient) => qc.getQueryData<WorkflowLibrary>(KEY)!;

describe("路径规则", () => {
  it("「在不在它下面」按段算,不是按前缀字符串", () => {
    expect(underPath("组/一.json", "组")).toBe(true);
    expect(underPath("组", "组")).toBe(true);
    expect(underPath("组里/一.json", "组"), "「组里」不是「组」底下的").toBe(false);
    expect(rebase("组/子/二.json", "组", "新组")).toBe("新组/子/二.json");
    expect(rebase("别的/一.json", "组", "新组")).toBe("别的/一.json");
  });
});

describe("先就地改", () => {
  it("新建:当场进左边那一列,不用等重问", () => {
    const qc = withData();
    libraryAddFolder(qc, KEY, "新组");
    expect(read(qc).folders).toEqual(["别的", "新组", "组", "组/子"]);
    //: 重复提交同一个名字不会写出两条(服务端那边本来就不让重名,这里只是别抖出两行)。
    libraryAddFolder(qc, KEY, "新组");
    expect(read(qc).folders?.filter((one) => one === "新组")).toHaveLength(1);
  });

  it("改名:它自己、子文件夹、里面每个文件的路径一起改", () => {
    const qc = withData();
    libraryRenameFolder(qc, KEY, "组", "新组");
    const after = read(qc);
    expect(after.folders).toEqual(["别的", "新组", "新组/子"]);
    expect(after.workflows?.map((one) => one.path)).toEqual(["a.json", "新组/一.json", "新组/子/二.json"]);
    expect(after.workflows?.find((one) => one.path === "新组/一.json")?.folder).toBe("新组");
    expect(after.workflows?.find((one) => one.path === "新组/子/二.json")?.folder).toBe("新组/子");
    expect(after.others?.[0].path).toBe("新组/说明.txt");
    expect(after.trash?.[0]).toMatchObject({ path: "新组/.trash/三.json", original: "新组/三.json" });
  });

  it("删掉:它和它底下的子文件夹一起从列表上拿掉", () => {
    const qc = withData();
    libraryRemoveFolder(qc, KEY, "组");
    const after = read(qc);
    expect(after.folders).toEqual(["别的"]);
    expect(after.workflows?.map((one) => one.path)).toEqual(["a.json"]);
  });

  it("挪一个文件:路径和它所属的文件夹一起改,别的文件不动", () => {
    const qc = withData();
    libraryMovePath(qc, KEY, "a.json", "组/a.json");
    const after = read(qc);
    expect(after.workflows?.find((one) => one.label === "A")).toMatchObject({ path: "组/a.json", folder: "组" });
    expect(after.workflows).toHaveLength(3);
  });

  it("手里还没有这一份(没打开过)时什么都不做,不凭空造一份空的", () => {
    const qc = new QueryClient();
    libraryAddFolder(qc, KEY, "新组");
    expect(qc.getQueryData(KEY)).toBeUndefined();
  });
});
