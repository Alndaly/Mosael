/**
 * 真机:白模运镜视频交给 Seedance,成片和白模几乎一模一样。提示词只说了「参考构图和运镜」,
 * 没说灰模只是占位、也没说画面里是什么 —— 模型唯一具体的画面就是那段灰模,于是照着画。
 */
import { describe, expect, it } from "vitest";

import { messages, type MessageKey } from "@/app/messages";

const zh = (key: MessageKey) => messages["zh-CN"][key];

import { sceneBriefPrompt, sceneInventory } from "./blockoutPrompt";

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
  it("画面里有什么、打光要说出来:白模里的形状各是什么", () => {
    const prompt = sceneBriefPrompt({ objects: OBJECTS, lighting: "正午日光", t: zh });
    expect(prompt).toContain("画面里有：列柱 ×2、神像");
    expect(prompt).toContain("打光：正午日光。");
    //: 白模说明由服务端随现渲的参考附上(ADR 0029),不在提示词框里重复一遍。
    expect(prompt).not.toContain("白模");
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
