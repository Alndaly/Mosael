/**
 * 按下 / 选中只有一个样子:`Button` / `IconButton` 写了 `aria-pressed`,「开着」的颜色就交给它(强调底色 + 强调色前景,
 * 描边的那种描边换淡强调色,见 components/ui/control-size 的 PRESSED)。
 *
 * 此前各处自己写:画板、工作流的工具条是 `bg-secondary text-foreground`,剪辑时间线是 `bg-accent`,素材库是
 * `border-primary/40 bg-accent text-primary`,定价是主色 12% 的底,还有按开关切变体的 `variant={on ? "secondary" : "ghost"}` ——
 * 同一个「开着」在相邻几页四个样子。这条拦:
 * - 写了 aria-pressed 的按钮,variant 是固定的一个(不按开关切);
 * - className 里不再写「开着」的颜色(底色 bg-accent / bg-secondary / 主色的混色、text-primary、text-accent-foreground、border-primary)。
 *
 * 存量:剪辑页播放器的循环键画在深色视频上,用的是白色半透明底 —— 那是视频上的控件条,不是界面上的工具条。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { describe, expect, it } from "vitest";

import { classText, openTags, readSource, tsxSources } from "@/design/jsxSource";

const OWNERS = ["components/ui/", "dev/"];
const KNOWN = new Set(["features/editor/Monitor.tsx"]);
const PRESSED_COLOR = /(?:^|\s)(?!(?:[\w-]+:)*(?:hover|focus|focus-visible|disabled|active):)(?:[\w-]+:)*(?:bg-(?:accent|secondary|primary\/\d+|\[color-mix[^\s]*)|text-primary|text-accent-foreground|border-primary(?:\/\d+)?)!?(?=\s|$)/;

export function pressedProblems(code: string): string[] {
  return openTags(code)
    .filter((tag) => (tag.tag === "Button" || tag.tag === "IconButton") && tag.attrs.has("aria-pressed"))
    .flatMap((tag) => {
      const problems: string[] = [];
      if (tag.attrs.get("variant")?.startsWith("{")) problems.push(`${tag.line}: variant 按开关切换 —— 写 aria-pressed 就够了`);
      const color = PRESSED_COLOR.exec(classText(tag.attrs.get("className")));
      if (color) problems.push(`${tag.line}: 自己写了「开着」的颜色 ${color[0].trim()}`);
      return problems;
    });
}

describe("按下态只有一个样子", () => {
  it("写了 aria-pressed 的按钮不自己画「开着」", () => {
    const found = tsxSources()
      .filter((file) => !OWNERS.some((owner) => file.startsWith(owner)) && !KNOWN.has(file))
      .flatMap((file) => pressedProblems(readSource(file)).map((problem) => `${file}:${problem}`));
    expect(found).toEqual([]);
  });

  it("认得出", () => {
    const code = [
      '<IconButton aria-pressed={on} className={cn(on && "bg-secondary text-foreground")} label="x" />',
      '<Button variant={on ? "secondary" : "ghost"} aria-pressed={on}>x</Button>',
      '<IconButton aria-pressed={on} className="text-muted-foreground" label="ok" />',
    ].join("\n");
    expect(pressedProblems(code)).toEqual(["1: 自己写了「开着」的颜色 bg-secondary", "2: variant 按开关切换 —— 写 aria-pressed 就够了"]);
  });
});
