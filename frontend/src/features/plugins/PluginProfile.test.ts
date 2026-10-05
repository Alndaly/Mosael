import { describe, expect, it } from "vitest";

import { foldedText, groupPermissions } from "@/features/plugins/PluginProfile";

describe("介绍折起来摆多少", () => {
  it("放得下就不折", () => {
    expect(foldedText("在百度网盘和素材库之间搬文件。")).toBeNull();
    expect(foldedText("x".repeat(260))).toBeNull();
  });

  it("中日韩一个字算两个宽:同样的宽度,中文截得比英文早一半", () => {
    expect(foldedText("字".repeat(131))).toBe(`${"字".repeat(130)}…`);
    expect(foldedText("x".repeat(261))).toBe(`${"x".repeat(260)}…`);
  });

  it("截在空格前,不留一个悬空的空格", () => {
    expect(foldedText(`${"x".repeat(259)} yz`, 260)).toBe(`${"x".repeat(259)}…`);
  });
});

describe("权限按种类分组", () => {
  const t = (key: string) => key;

  it("联网的列服务名,文件的说读还是写,程序一条;顺序固定(联网、文件、程序、其他)", () => {
    const groups = groupPermissions(t as never, ["process:spawn", "filesystem:write", "network:comfyui", "network:localhost", "filesystem:read"]);
    expect(groups.map((group) => group.kind)).toEqual(["network", "filesystem", "process"]);
    expect(groups[0].items).toEqual([
      { code: "network:comfyui", label: "comfyui" },
      { code: "network:localhost", label: "pluginPermLocalServices" },
    ]);
    expect(groups[1].items.map((item) => item.label)).toEqual(["pluginPermWriteFiles", "pluginPermReadFiles"]);
    expect(groups[2].items).toEqual([{ code: "process:spawn", label: "pluginPermStartPrograms" }]);
  });

  it("认不出的归「其他」,照原样显示码 —— 不猜", () => {
    expect(groupPermissions(t as never, ["assets:read", "filesystem:exec"])).toEqual([
      { kind: "filesystem", items: [{ code: "filesystem:exec", label: "filesystem:exec" }] },
      { kind: "other", items: [{ code: "assets:read", label: "assets:read" }] },
    ]);
  });
});
