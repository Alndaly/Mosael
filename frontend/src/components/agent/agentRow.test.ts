import { describe, expect, it } from "vitest";

import { AGENT_ROW_BODY_CLASS, AGENT_ROW_CLASS, AGENT_ROW_ICON_CLASS } from "./agentRow";

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
