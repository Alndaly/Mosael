/**
 * 画布上的手势守卫:**别把整块地方从画布手里抢走**。
 *
 * React Flow 用三个类名让出交互:`nodrag`(不拖节点)、`nopan`(不平移画布)、`nowheel`
 * (不缩放/不滚动画布)。它们该挂在**真的要吞掉那个手势的控件**上 —— 进度条要吞拖动,
 * 所以进度条挂 nodrag。挂错地方的代价很具体,而且这个文件里已经犯过三次:
 *
 *  · 整块容器挂 nodrag → 「视频节点无法拖动」
 *  · 盖住全屏的播放键挂 nodrag → 同上
 *  · 控件条挂 nowheel → 「滚动到播放条的时候会停下」(那条带子 40px 高、横跨整个节点,
 *    还因为 translate-y-full 悬在节点下方,没悬浮时也一直挡着)
 *
 * 播放器里没有任何可滚动的区域,所以它**永远不需要 nowheel**。这条钉住它。
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const SRC = path.join(__dirname, "..", "..");
//: 播放器的家当已经搬进 components/app/media-playback(画板/灯箱/工具结果共用),
//: 这两条规定扫的是它,不是画板剩下的薄封装。
const PLAYER = path.join(SRC, "components/app/media-playback.tsx");

describe("画布上的播放器不抢手势", () => {
  it("播放器里不出现 nowheel —— 它没有可滚动的地方,挂上就是把画布的滚轮吞掉", () => {
    const source = fs.readFileSync(PLAYER, "utf8");
    const offenders = source
      .split("\n")
      .map((line, at) => ({ line, at: at + 1 }))
      .filter(({ line }) => /className=|cn\(/.test(line) && /\bnowheel\b/.test(line));
    expect(offenders.map((one) => `${one.at}: ${one.line.trim()}`)).toEqual([]);
  });

  it("藏起来的控件条要连指针事件一起收掉 —— 透明不等于不吃事件", () => {
    const source = fs.readFileSync(PLAYER, "utf8");
    const bar = source.split("\n").find((line) => line.includes("translate-y-full") && line.includes("opacity-0"));
    expect(bar, "找不到那条控件条了(改名了?)").toBeTruthy();
    expect(bar).toContain("pointer-events-none");
  });
});
