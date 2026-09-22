import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * 棘轮:**画布上的叠放顺序不许在调用处现挑一个数。**
 *
 * 「旗子压在所有内容之上」是一条规则。而它此前在两块画布上各自变成了一个凭手感挑的常数:
 * 画板写 `zIndex: 2`,工作流写 `zIndex: 950`。两个数不是谁错了 —— 是**那条规则没有写在
 * 任何地方**,于是每块画布各挑一个,而加一种新节点类型时,该挑几没有参照系可查。
 *
 * 表现也不报错:某种节点盖住旗子,点不到;而且只在特定内容下才出现。
 *
 * 判据:`features/` 下不许出现字面量 `zIndex: <数>`,要给就从本画布的 `LAYERS` 表里取 ——
 * 那张表把本画布的每一层写在一起,于是"最上面是哪一层"这件事有地方可查,也有地方可改。
 * (CSS 的 `z-index` 是另一回事:那是 DOM 的堆叠上下文,和 React Flow 的节点序无关。)
 *
 * **扫之前先剥注释。** 解释这次改动的注释里正好引用了它要禁的那个写法 —— 断言当场打到
 * 自己身上。这个错这一轮在后端犯过五次,那边为此有了 `tests/util.executable_source`;
 * 这里是同一件事的前端一侧。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单。
export const RATCHET = true;

const FEATURES = join(import.meta.dirname);

/** 会被执行的那部分源码 —— 行注释和块注释都剥掉。 */
function executable(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
}

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(path) && !path.includes(".test.") ? [path] : [];
  });
}

describe("画布的叠放顺序", () => {
  it("扫描面站得住 —— 确实扫到了功能模块的源码", () => {
    // 走空目录的话,下面那条断言天然成立。
    const files = sources(FEATURES);
    expect(files.length).toBeGreaterThan(100);
    expect(files.some((one) => one.includes("BoardCanvas"))).toBe(true);
  });

  it("不许在调用处写死一个 zIndex —— 从本画布的 LAYERS 表里取", () => {
    const offenders: string[] = [];
    for (const file of sources(FEATURES)) {
      const code = executable(readFileSync(file, "utf8"));
      const where = file.slice(FEATURES.length + 1);
      // 对象字面量里的:`{ ..., zIndex: 2 }`
      for (const match of code.matchAll(/zIndex:\s*(-?\d+)/g)) {
        offenders.push(`${where} → zIndex: ${match[1]}`);
      }
      // **也要管参数位。** 第一版只扫对象字面量 —— 把数字从 `{ zIndex: 2 }` 挪进
      // `toMarkerNodes(xs, 2)` 就绕过去了,而那正是这次改动之后它会长的样子。实测:
      // 变异验证时改成 `toMarkerNodes([marker], 3)`,棘轮是绿的。
      for (const match of code.matchAll(/toMarkerNodes\([^()]*,\s*(-?\d+)\s*\)/g)) {
        offenders.push(`${where} → toMarkerNodes(…, ${match[1]})`);
      }
    }
    expect(
      offenders,
      "把它写进本画布的 LAYERS 表(见 boards/BoardCanvas.tsx 与 workflows/workflowCanvasModel.ts):" +
        "一个孤零零的数说不出它压在谁之上,而下一个人只能再挑一个。",
    ).toEqual([]);
  });

  it("两块画布都还有 LAYERS 表 —— 规则要有地方可查", () => {
    for (const file of ["boards/BoardCanvas.tsx", "workflows/workflowCanvasModel.ts"]) {
      expect(readFileSync(join(FEATURES, file), "utf8"), `${file} 里没有 LAYERS 表`).toContain("const LAYERS = {");
    }
  });
});
