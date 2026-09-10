import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { AGENT_ROW_BODY_CLASS, AGENT_ROW_CLASS, AGENT_ROW_ICON_CLASS, AGENT_TEXT_BLOCK_CLASS } from "./agentRow";

/** Tailwind 的间距刻度:1 = 4px。 */
const px = (step: number) => step * 4;

/**
 * 时间线里**标题和它展开的正文必须落在同一个内容起点上**。
 *
 * 这两个数分别藏在两串类名里(行外框的 gap、正文的 ml/pl),隔着几十行代码,谁都看不出它们
 * 有关系 —— 于是「gap 看着不一致」就成了一个很容易被顺手抹平的东西(这次就抹平过一次,
 * 结果是标题比自己的正文右偏 4px)。这条把那段算术钉下来:改一个,另一个必须跟着改。
 */
function contentX(rowClass: string, bodyClass: string) {
  const paddingLeft = px(Number(/px-(\d+(?:\.\d+)?)/.exec(rowClass)![1]));
  const gap = px(Number(/gap-(\d+(?:\.\d+)?)/.exec(rowClass)![1]));
  const icon = 16; // MarkerIcon 的槽宽(size-4),里面居中放一枚 size-3 的图标
  const marginLeft = Number(/ml-\[(\d+)px\]/.exec(bodyClass)![1]);
  const border = 1; // border-l
  const bodyPadding = px(Number(/pl-(\d+(?:\.\d+)?)/.exec(bodyClass)![1]));
  return { title: paddingLeft + icon + gap, body: marginLeft + border + bodyPadding };
}

describe("时间线一行的几何", () => {
  it("标题和展开的正文同一个起点", () => {
    const { title, body } = contentX(AGENT_ROW_CLASS, AGENT_ROW_BODY_CLASS);
    expect(title).toBe(body);
  });

  it("竖线落在图标中线上 —— 明细看起来是从这一步垂下来的", () => {
    const paddingLeft = px(Number(/px-(\d+(?:\.\d+)?)/.exec(AGENT_ROW_CLASS)![1]));
    const rule = Number(/ml-\[(\d+)px\]/.exec(AGENT_ROW_BODY_CLASS)![1]);
    // 图标槽是 paddingLeft..paddingLeft+16,中线在 +8;差一两个像素还看得过去,再多就歪了。
    expect(Math.abs(rule - (paddingLeft + 8))).toBeLessThanOrEqual(1);
  });

  it("图标显式带尺寸 —— 否则 Marker 会把它撑到 16px,行的节奏就变了", () => {
    expect(AGENT_ROW_ICON_CLASS).toMatch(/^size-\d+$/);
  });
});

/**
 * **一轮里"一个空行"只能有一种宽度。**
 *
 * 标记行自带 `py-1` 的热区,正文段落没有 —— 外层那一个统一的 gap 于是在不同的邻居之间看着是
 * 三个值(实测 780px 宽的一轮:正文↔标记行 18px、标记行↔标记行 **22px**)。给正文块补上同一份
 * 内缩,三种邻居才收敛成一个数(改完实测 18 / 18.5 / 18 / 18)。
 */
describe("块与块之间只有一种间距", () => {
  const py = (cls: string) => {
    const step = /(?:^|\s)py-(\d+(?:\.\d+)?)/.exec(cls);
    return step ? Number(step[1]) * 4 : 0;
  };

  it("正文块和标记行有同一份上下内缩", () => {
    expect(py(AGENT_TEXT_BLOCK_CLASS)).toBe(py(AGENT_ROW_CLASS));
  });

  it("容器的 gap 加上两侧内缩,仍是原先最常见的那一档", () => {
    // 收窄 gap 是为了"只把 22 那一档收回来",不是把整体压扁:18 = 6(gap-1.5) + 4 + 4 + 字体度量。
    const source = readFileSync(join(import.meta.dirname, "ToolCalls.tsx"), "utf8");
    const gap = /grid w-full min-w-0 grid-cols-\[minmax\(0,1fr\)\] gap-(\d+(?:\.\d+)?)/.exec(source);
    expect(gap, "AgentTurnContent 的容器该用一个统一的 gap").not.toBeNull();
    expect(Number(gap![1]) * 4 + py(AGENT_TEXT_BLOCK_CLASS) + py(AGENT_ROW_CLASS)).toBe(14);
  });

  it("正文块真的用上了那份内缩", () => {
    const source = readFileSync(join(import.meta.dirname, "ToolCalls.tsx"), "utf8");
    expect(source).toContain("className={AGENT_TEXT_BLOCK_CLASS}");
  });
});
