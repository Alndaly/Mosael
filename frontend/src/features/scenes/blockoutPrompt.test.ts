/**
 * 真机:白模运镜视频交给 Seedance,成片和白模几乎一模一样。提示词只说了「参考构图和运镜」,
 * 没说灰模只是占位、也没说画面里是什么 —— 模型唯一具体的画面就是那段灰模,于是照着画。
 */
import { describe, expect, it } from "vitest";

import { messages, type MessageKey } from "@/app/messages";

const zh = (key: MessageKey) => messages["zh-CN"][key];

import { blockoutPrompt, sceneInventory } from "./blockoutPrompt";

const OBJECTS = [
  { id: "a", parent_id: null, name: "列柱", kind: "cylinder", hidden: false },
  { id: "b", parent_id: null, name: "列柱", kind: "cylinder", hidden: false },
  { id: "c", parent_id: null, name: "神像", kind: "model", hidden: false },
  { id: "d", parent_id: null, name: "Box 3", kind: "box", hidden: false },
  { id: "e", parent_id: null, name: "主机位", kind: "camera", hidden: false },
  { id: "f", parent_id: null, name: "顶光", kind: "light", hidden: false },
  { id: "g", parent_id: null, name: "藏起来的道具", kind: "box", hidden: true },
] as const;

describe("白模 → 生成的提示词", () => {
  it("视频:说清白模只是占位,只取运镜与位置,成片要写实", () => {
    const prompt = blockoutPrompt({ kind: "video", sceneName: "巨型神殿 · 列柱大厅", objects: OBJECTS, lighting: "正午日光", clay: true, t: zh });
    expect(prompt).toContain("白模预演");
    expect(prompt).toContain("只沿用它的运镜");
    expect(prompt).toContain("不要出现灰模");
    expect(prompt).toContain("打光：正午日光。");
    // 视频路径没有第二张灰模参考图 —— 不能指着一个不存在的输入说话。
    expect(prompt).not.toContain("另一张灰模参考图");
  });

  it("画面里有什么要说出来:白模里的形状各是什么", () => {
    const prompt = blockoutPrompt({ kind: "video", sceneName: "S", objects: OBJECTS, lighting: "x", clay: false, t: zh });
    expect(prompt).toContain("画面里有：列柱 ×2、神像");
  });

  it("出图附了灰模渲染时,才提那张灰模参考图", () => {
    expect(blockoutPrompt({ kind: "image", sceneName: "S", objects: [], lighting: "x", clay: true, t: zh })).toContain("另一张灰模参考图");
    expect(blockoutPrompt({ kind: "image", sceneName: "S", objects: [], lighting: "x", clay: false, t: zh })).not.toContain("另一张灰模参考图");
  });

  it("清单不列相机、灯、藏起来的和默认名", () => {
    expect(sceneInventory(OBJECTS, zh)).toBe("列柱 ×2、神像");
    expect(sceneInventory([{ id: "o", parent_id: null, name: "Object", kind: "box", hidden: false }], zh)).toBe("");
  });

  it("藏起来的组里的东西也不列 —— 它们自己那一位没藏,但画面里同样没有", () => {
    const objects = [
      { id: "g", parent_id: null, name: "后排", kind: "group", hidden: true },
      { id: "p", parent_id: "g", name: "石像", kind: "box", hidden: false },
      { id: "q", parent_id: null, name: "祭台", kind: "box", hidden: false },
    ] as const;
    expect(sceneInventory(objects, zh)).toBe("祭台");
  });
});
