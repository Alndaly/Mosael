/**
 * 加载占位一律走 components/ui/skeleton 的扫光,不再有各写各的 animate-pulse 灰块。
 *
 * 用户报「loading 状态的卡片 Skeleton 有问题,我希望是一个滚动的那种特效」。当时占位块的样子
 * 散在两处:Skeleton 自己挂 `animate-pulse`,画板生成中的那一格又在调用处挂 `animate-none` 把它
 * 关掉 —— 于是整张卡是一块死灰,只有中间一个小圈在转。扫光收进 design/tokens.css 的 `.skeleton`
 * 之后,想让某块占位"不一样"只剩一条路:改那一处,所有占位一起变。
 *
 * 这里守两件事:
 * 1. `animate-pulse` 只许出现在点名的**状态指示**上(运行中的小圆点、图标),那是"它活着",不是
 *    "内容在来的路上"。新写一块脉冲灰块当占位会在这里挂掉 —— 用 <Skeleton>。
 * 2. 调用 <Skeleton> 时不在 className 里改它的动画或底色(`animate-*` / `bg-*`)。
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单。
export const RATCHET = true;

const SRC = path.resolve(import.meta.dirname, "..");

/** 可以脉冲的地方 —— 每一处都是状态指示,不是加载占位。 */
const PULSE_ALLOWED: Record<string, string> = {
  "features/agent/SubagentPanel.tsx": "子代理运行中的状态圆点",
  "features/agent/StatusIcon.tsx": "运行中的状态图标",
};

function sources(): Array<[string, string]> {
  const found: Array<[string, string]> = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (/\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) {
        found.push([path.relative(SRC, full), fs.readFileSync(full, "utf8")]);
      }
    }
  };
  walk(SRC);
  return found.sort();
}

/** 去掉注释:说明里常常正写着"此前挂了 animate-pulse"。 */
const code = (text: string) => text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

describe("加载占位", () => {
  const files = sources();

  it("animate-pulse 只留在点名的状态指示上", () => {
    const offenders = files
      .filter(([file, text]) => /\banimate-pulse\b/.test(code(text)) && !(file in PULSE_ALLOWED))
      .map(([file]) => file);
    expect(offenders, "加载占位请用 <Skeleton>(扫光);状态指示才可以脉冲,并在这里点名").toEqual([]);
  });

  it("点名的豁免都还在用 —— 不留过期的条目", () => {
    const byFile = new Map(files);
    for (const file of Object.keys(PULSE_ALLOWED)) {
      expect(code(byFile.get(file) ?? ""), file).toMatch(/\banimate-pulse\b/);
    }
  });

  it("<Skeleton> 的调用处不改它的动画和底色", () => {
    const offenders: string[] = [];
    for (const [file, text] of files) {
      for (const match of code(text).matchAll(/<Skeleton\b([^>]*)>/g)) {
        const props = match[1];
        if (/\b(animate|bg)-[\w[]/.test(props)) offenders.push(`${file}: ${props.trim().slice(0, 100)}`);
      }
    }
    expect(offenders, "扫光和底色归 design/tokens.css 的 .skeleton 管").toEqual([]);
  });

  it("确实有地方在用它 —— 扫描面没有空转", () => {
    const users = files.filter(([, text]) => /<Skeleton\b/.test(text)).length;
    expect(users).toBeGreaterThan(5);
  });
});
