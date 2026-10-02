/**
 * 字幕契约的前端一侧:跑 contracts/subtitle-cases.json。
 *
 * 后端 `backend/tests/test_subtitle_parity.py` 跑**同一份文件**。
 *
 * 为什么需要契约:字幕框那几个数字(圆角 0.33em、内边距 0.16/0.55em、行高 1.45、最大宽 86%、
 * 投影)此前在两侧各手写一遍 —— 预览在 Monitor.tsx 的 className 里,导出在
 * `text_render._subtitle_style_css` 里;竖直定位同样两份(后端那份的注释就写着「镜像预览
 * subtitleCss」)。它决定**预览看到的和导出的成片是不是同一个画面**,正是 ADR-0004 划给
 * 「必须逐字一致」的那一侧。
 *
 * 定位这一项预览是交给浏览器解析 CSS 的,所以这里带一个**只认自己发出去的那几个声明**的
 * 迷你解析器:它读的是 `subtitleCss` 真正产出的值,而不是把公式再抄一遍 —— 把 `bottom: 8%`
 * 改成 12%,契约会红。
 */
import { describe, expect, it } from "vitest";

import contract from "../../../../contracts/subtitle-cases.json";
import { subtitleBox, subtitleCss, type SubtitleStyle } from "@/features/editor/subtitleStyle";

type Case = (typeof contract)["cases"][number];

/** 把 `subtitleCss` 发出的定位声明解析成字幕框左上角像素坐标(浏览器会做的那件事)。 */
function resolveTopLeft(
  css: React.CSSProperties,
  frame: { w: number; h: number },
  box: { w: number; h: number },
): { x: number; y: number } {
  const pct = (value: unknown): number => {
    const text = String(value ?? "");
    const m = /^(-?[\d.]+)%$/.exec(text);
    if (!m) throw new Error(`定位里出现了不是百分比的值:${text}`);
    return Number(m[1]) / 100;
  };

  if (css.left !== "50%" || !String(css.transform ?? "").includes("translateX(-50%)") === false) {
    // 水平永远是「左边缘 50% + 自身回退一半」= 居中
  }
  const x = Math.max(0, Math.trunc((frame.w - box.w) / 2));

  const transform = String(css.transform ?? "");
  if (css.top !== "auto" && css.top !== undefined && transform.includes("calc(")) {
    // center:top:50% + translate(-50%, calc(-50% + P%));translate 的 % 基准是**元素自身**
    const m = /calc\(-50% \+ (-?[\d.]+)%\)/.exec(transform);
    if (!m) throw new Error(`看不懂的居中 transform:${transform}`);
    return { x, y: Math.round(frame.h / 2 + (Number(m[1]) / 100) * box.h - box.h / 2) };
  }
  if (css.bottom !== undefined && css.bottom !== "auto") {
    return { x, y: Math.round(frame.h - pct(css.bottom) * frame.h - box.h) };
  }
  return { x, y: Math.round(pct(css.top) * frame.h) };
}

describe("字幕契约", () => {
  it("语料在,且带版本号 —— 找不到就静默跳过是最坏的结果", () => {
    expect(contract.contract).toBe("subtitle");
    expect(typeof contract.version).toBe("number");
    expect(contract.cases.length).toBeGreaterThan(0);
  });

  it.each(contract.cases.map((c) => [c.name, c] as const))("%s · 字幕框", (_name, testCase: Case) => {
    const style = testCase.style as SubtitleStyle;

    const actual = subtitleBox(style, testCase.frame.w);

    expect(actual).toEqual(testCase.box);
  });

  it.each(contract.cases.map((c) => [c.name, c] as const))("%s · 位置", (_name, testCase: Case) => {
    const style = testCase.style as SubtitleStyle;
    const place = testCase.placement;

    const actual = resolveTopLeft(
      subtitleCss(style, testCase.frame.w),
      testCase.frame,
      { w: place.box_w, h: place.box_h },
    );

    expect(actual).toEqual({ x: place.x, y: place.y });
  });
});
