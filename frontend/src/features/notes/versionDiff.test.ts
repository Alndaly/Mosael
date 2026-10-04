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

it("整行换成不相干的字:画成删一段、加一段,不逐字交错", () => {
  expect(diffDocument("开头\n咖啡馆里,剪辑师打开笔记本。\n结尾", "开头\n画面回到窗前,灯熄灭。\n结尾")).toEqual([
    { kind: "same", lines: ["开头"] },
    { kind: "change", segments: [{ kind: "del", text: "咖啡馆里,剪辑师打开笔记本。" }] },
    { kind: "change", segments: [{ kind: "ins", text: "画面回到窗前,灯熄灭。" }] },
    { kind: "same", lines: ["结尾"] },
  ]);
});

it("在一段后面接着写,还是按字画出新加的那一截", () => {
  expect(diffDocument("周一开会。", "周一开会。会上定了开场要提速。")).toEqual([
    { kind: "change", segments: [{ kind: "same", text: "周一开会。" }, { kind: "ins", text: "会上定了开场要提速。" }] },
  ]);
});

it("一样的两段没有改动块", () => {
  expect(diffDocument("一\n二", "一\n二")).toEqual([{ kind: "same", lines: ["一", "二"] }]);
  expect(diffDocument("", "")).toEqual([]);
});
