/**
 * 3D 场景舞台的上下分:视口至少占一半,关键帧表让。
 *
 * 关键帧表的高度是人拖出来的(默认 300px)。1024×700 的窗口里此前它和外面那层 .scene-timeline 都不缩,
 * 视口被压成 194px 的一条(真浏览器量过);改成能缩之后视口 296px、关键帧表 198px,1440×900 下照旧 434 / 300。
 * jsdom 没有版面,这里钉住那三条声明 —— 哪一条被改回去,矮窗口就又挤坏了。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(import.meta.dirname, "scenes.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

/** 第一个以这个选择器开头的规则块里的声明。 */
function block(selector: string): string {
  const start = css.indexOf(`${selector} {`);
  expect(start, selector).toBeGreaterThanOrEqual(0);
  return css.slice(start, css.indexOf("}", start));
}

describe("舞台的上下分", () => {
  it("视口至少占舞台的一半", () => {
    expect(block(".scene-viewport")).toMatch(/min-height:\s*max\(180px,\s*50%\)/);
  });

  it("关键帧表和外面那层都能缩(各自有最矮)", () => {
    expect(block(".scene-timeline")).toMatch(/flex-shrink:\s*1/);
    expect(block(".scene-timeline")).toMatch(/min-height:\s*0/);
    expect(block(".scene-dope")).toMatch(/flex-shrink:\s*1/);
    expect(block(".scene-dope")).toMatch(/min-height:\s*160px/);
  });
});
