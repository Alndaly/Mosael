import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * 加载占位块的底色必须**相对它所在的那层表面**算,不能是一个固定的灰;动起来靠扫过的光,不靠脉冲。
 *
 * 更早是 `bg-muted` —— 页面的次级底色。而占位块也出现在弹层上(插件市场就在 ModalShell 里),
 * 弹层的表面比页面**更浅**,于是两者几乎同色:实测对比 1.07(浅色)/ 1.14(深色),再叠上
 * animate-pulse 的透明度起伏,眼睛完全看不出那儿有东西。用户报的「加载中没有 Skeleton」
 * 其实是有,只是看不见。换成前景色 12% 的叠加之后,三种表面(页面 / 卡片 / 弹层)上都是同一个
 * 相对差:实测 1.25–1.26(浅色)、1.38–1.42(深色)。
 *
 * 之后用户又报「loading 状态的卡片 Skeleton 有问题,我希望是一个滚动的那种特效」:脉冲换成了
 * 扫光,样子收进 design/tokens.css 的 `.skeleton`。编出来的规则在 design/compiledCascade.test.ts
 * 里核对,调用处的写法由 design/skeletons.test.ts 守着。
 *
 * jsdom 不做颜色合成,所以这里钉的是**取色的方式**,不是最终对比度。
 */
/** 去掉注释 —— 注释里正写着"更早是 bg-muted",不去掉的话这条棘轮会被自己的说明喂饱。 */
const stripComments = (text: string) => text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
const source = stripComments(readFileSync(join(import.meta.dirname, "skeleton.tsx"), "utf8"));
const tokens = stripComments(readFileSync(join(import.meta.dirname, "..", "..", "design", "tokens.css"), "utf8"));

/** 某个主题块(`:root` / `.dark`)的正文。 */
function themeBlock(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = tokens.match(new RegExp(`^${escaped} \\{([\\s\\S]*?)\\n\\}`, "m"));
  if (!match) throw new Error(`tokens.css 里没有 ${selector} 主题块`);
  return match[1];
}

describe("加载占位块", () => {
  it("用设计系统的 .skeleton,不在组件里自己拼底色和动画", () => {
    expect(source).toMatch(/cn\("skeleton\b/);
    expect(source).not.toMatch(/\bbg-[a-z]/);
    expect(source).not.toMatch(/\banimate-/);
  });

  it("两套主题的底色都是前景色的低透明度叠加 —— 合成在当前这层上", () => {
    for (const theme of [":root", ".dark"]) {
      expect(themeBlock(theme), theme).toMatch(/--skeleton-base:\s*color-mix\(in srgb, var\(--foreground\) 1\d%, transparent\)/);
      expect(themeBlock(theme), theme).toMatch(/--skeleton-highlight:/);
    }
  });

  it("底色不吃任何一个固定的表面 token", () => {
    // 这些都是"某一层"的底色:占位块一旦踩到别的层上就没了。
    const base = [themeBlock(":root"), themeBlock(".dark")]
      .flatMap((block) => block.match(/--skeleton-base:[^;]*;/g) ?? [])
      .join("\n");
    for (const token of ["--muted", "--secondary", "--card", "--popover", "--accent", "--panel"]) {
      expect(base, `${token} 是某一层自己的底色,不能拿来当占位块`).not.toContain(`var(${token})`);
    }
  });
});
