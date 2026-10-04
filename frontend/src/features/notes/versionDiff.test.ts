import { expect, it } from "vitest";
import { diffDocument } from "./versionDiff";

it("没改的行原样成段,改了的那几行按字对齐", () => {
  expect(diffDocument("# 周报\n\n周一开会。\n\n周二写脚本。", "# 周报\n\n周一和剪辑组开会。\n\n周二写脚本。")).toEqual([
    { kind: "same", lines: ["# 周报", ""] },
    { kind: "change", segments: [{ kind: "same", text: "周一" }, { kind: "ins", text: "和剪辑组" }, { kind: "same", text: "开会。" }] },
    { kind: "same", lines: ["", "周二写脚本。"] },
  ]);
});

it("中间删一行、末尾加一行,各是一块", () => {
  expect(diffDocument("一\n二\n三", "一\n三\n四")).toEqual([
    { kind: "same", lines: ["一"] },
    { kind: "change", segments: [{ kind: "del", text: "二" }] },
    { kind: "same", lines: ["三"] },
    { kind: "change", segments: [{ kind: "ins", text: "四" }] },
  ]);
});

it("一样的两段没有改动块", () => {
  expect(diffDocument("一\n二", "一\n二")).toEqual([{ kind: "same", lines: ["一", "二"] }]);
  expect(diffDocument("", "")).toEqual([]);
});
