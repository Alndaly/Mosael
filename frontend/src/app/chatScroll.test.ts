/**
 * 结构性约束:**装智能体正文的滚动容器,横向也要锁死。**
 *
 * 这类容器里会出现模型吐的代码块、长 URL、宽表格。而 flex / grid 的子项默认是
 * `min-width: auto` —— 它们**不会**被压缩到内容宽度以下,于是一段长代码把整列撑宽,
 * 整个对话面板就能左右滚,正文跟着晃。
 *
 * 容易被漏掉是因为**代码块自己已经写了 `overflow-x-auto`**,看起来该管的都管了。但那条只在
 * 父容器被约束时才生效:父容器没有上限,`<pre>` 就直接长出去,没有可滚的余地。所以必须
 * 成对出现 —— `min-w-0`(允许被压缩)+ `overflow-x-hidden`(兜住越界的那一点)。
 *
 * 这条查的是**同时写了 overflow-y-auto 的容器**:它已经声明了"内容会超出",横向却没表态。
 * 例外写进 EXEMPT 并说明理由 —— 只减不增,和 buttonPending.test.ts 同一套棘轮。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const SRC = path.resolve(__dirname, "..");

/** 只查真正承载对话正文的文件 —— 别的滚动容器(设置页表单、列表)不适用这条。 */
const FILES = [
  "components/agent/CanvasAgentChat.tsx",
  "features/ai-studio/ChatWorkspace.tsx",
  "components/agent/ToolCalls.tsx",
];

/** `<文件>:<片段>` → 为什么不需要锁横向。 */
const EXEMPT: Record<string, string> = {};

/** 抓出所有带 overflow-y-auto 的 className 字符串。 */
function scrollContainers(text: string): string[] {
  return [...text.matchAll(/"([^"]*overflow-y-auto[^"]*)"/g)].map((m) => m[1]);
}

describe("智能体对话的滚动容器锁死横向", () => {
  it("每个纵向滚动容器都对横向表了态", () => {
    const missing: string[] = [];
    for (const rel of FILES) {
      const text = fs.readFileSync(path.join(SRC, rel), "utf8");
      for (const cls of scrollContainers(text)) {
        // 宽度写死的容器撑不开(Radix 弹层这类),不适用这条。
        if (/\bw-\[/.test(cls)) continue;
        // 锁住横向:overflow-hidden 本身就覆盖双轴,overflow-x-* 是显式写法。
        const locked = /overflow-hidden|overflow-x-(hidden|auto)/.test(cls);
        // 允许被压缩:否则 min-width:auto 会让子项拒绝收缩,上面那条根本没有生效余地。
        const shrinkable = cls.includes("min-w-0") || cls.includes("minmax(0,1fr)");
        if (locked && shrinkable) continue;
        const key = Object.keys(EXEMPT).find((k) => k.startsWith(`${rel}:`) && cls.includes(k.slice(rel.length + 1)));
        if (key) continue;
        missing.push(`${rel}: ${cls.slice(0, 90)}…`);
      }
    }
    expect(missing).toEqual([]);
  });

  it("豁免清单里没有过时条目", () => {
    const stale = Object.keys(EXEMPT).filter((key) => {
      const [rel, ...rest] = key.split(":");
      const fragment = rest.join(":");
      return !fs.readFileSync(path.join(SRC, rel), "utf8").includes(fragment);
    });
    expect(stale).toEqual([]);
  });
});

/**
 * 结构性约束:**智能体正文的单列 grid 必须显式给轨道。**
 *
 * `grid` 不写 `grid-template-columns` 时,隐式列是 `auto` —— 也就是
 * `minmax(min-content, max-content)`。一段不可断的长串(一条 URL、一个 32 位 session id)
 * 会把轨道撑到 max-content 并**溢出**外层那 780px 的气泡;更要命的是同一个 grid 里的其它块
 * (思考块、工具卡)被拉伸到同一个轨道宽度,于是**一起**变宽,而正文因为自己会断词仍是 780。
 * 呈现出来就是"一条消息里几块内容宽度不一,中间那几块凸出来"。
 *
 * 真机上量过:摘掉轨道声明后,同一段长 URL 把子项撑到 1511px(外层气泡仍是 780)。
 * 子项自己的 truncate 救不了 —— truncate 要父级先有确定宽度,而这里父级宽度正由内容决定。
 */
describe("智能体正文的单列 grid 显式约束轨道", () => {
  const AGENT_TURN = path.join(SRC, "components/agent/ToolCalls.tsx");

  it("AgentTurnContent 的容器给了 minmax(0,1fr)", () => {
    const text = fs.readFileSync(AGENT_TURN, "utf8");
    const body = text.slice(text.indexOf("export function AgentTurnContent"));
    const root = body.match(/className="(grid[^"]*)"/);
    expect(root, "AgentTurnContent 的根容器不再是 grid?那这条约束要跟着改").not.toBeNull();
    expect(root![1]).toContain("grid-cols-[minmax(0,1fr)]");
  });
});
