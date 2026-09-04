/**
 * 锁了行轴就得锁列轴 —— 只写 `grid-rows` 会让隐式列按 max-content 定尺。
 *
 * `grid-rows-[auto_minmax(0,1fr)_auto]` 这种写法是在说「中间那行可以被压扁」。作者显然想过
 * 尺寸约束,但只想了一个方向:没声明 `grid-template-columns` 时,列走**隐式轨道**,尺寸函数
 * 是 `auto` —— 它的基础尺寸取子项的 **min-content 贡献**。子项里只要有一段 `nowrap`
 * (`truncate` 自带),这个贡献就是整串文字的宽度,于是整列被撑到内容宽度。
 *
 * 后果分两种长相,同一个成因:
 *
 *     外框有定宽(停靠面板)   内容被 overflow-hidden 一刀切,`truncate` 永不触发 —— 因为
 *                            它压根没被压缩过,省略号出不来,右端的按钮被推出可视区
 *     外框能长(悬浮面板)     面板自己被撑宽,看着像「窗口被内容顶开」
 *
 * 智能体面板(`components/agent/CanvasAgentChat.tsx`)两种都中过:停靠时标题被硬裁、新建/
 * 停靠/关闭三个按钮整体消失,悬浮时窗口宽到 885px。`features/ai-studio/ChatWorkspace.tsx`
 * 也撞过同一下,当时是给那一行子项补 `min-w-0` —— 有效,但只护住了那一行。
 *
 * 两种修法都能让轨道回到容器宽度(实测都行):
 *
 *     容器上 `grid-cols-[minmax(0,1fr)]`   一次护住所有行,推荐
 *     子项上 `min-w-0`                     只护住写了的那一个
 *
 * 这条棘轮拦的是「下一处又只声明一个轴」。存量冻结在 GRANDFATHERED —— 它们**不是已知有
 * bug**,只是这次没有逐个复核;复核过并补上轴声明后,从清单里删掉一行,棘轮就收紧一格。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");

/**
 * 存量:声明了行轴、没声明列轴的元素,记成 `文件:类名片段`。
 *
 * **只减不增。** 新增一处会红,提示两轴一起声明;修好一处后不删这里也会红。
 */
const GRANDFATHERED = new Set<string>([
  "components/agent/SubagentPanel.tsx: grid-rows-[auto_minmax(0,1fr)]",
  "features/ai-studio/AiStudio.tsx: grid-rows-[minmax(0,1fr)_auto]",
  "features/ai-studio/ChatWorkspace.tsx: grid-rows-[auto_minmax(0,1fr)_auto]",
  "features/ai-studio/trace/TraceView.tsx: grid-rows-[auto_auto_minmax(0,1fr)]",
  "features/ai-studio/trace/TraceView.tsx: grid-rows-[auto_auto_minmax(0,1fr)_auto]",
  "features/auth/LoginView.tsx: grid-rows-[minmax(0,1fr)_auto]",
  "features/boards/BoardCollaborationDialog.tsx: grid-rows-[auto_minmax(0,1fr)]",
  "features/browser-pool/BrowserPoolView.tsx: grid-rows-[auto_minmax(0,1fr)]",
  "features/editor/EditorView.tsx: grid-rows-[auto_minmax(0,1fr)]",
  "features/editor/Inspector.tsx: grid-rows-[auto_minmax(0,1fr)]",
  "features/editor/Monitor.tsx: grid-rows-[minmax(0,1fr)_auto_auto]",
  "features/editor/timeline/Timeline.tsx: grid-rows-[auto_minmax(0,1fr)]",
  "features/media/AssetCompareView.tsx: grid-rows-[minmax(0,1fr)_auto]",
  "features/media/AssetCompareView.tsx: grid-rows-[auto_minmax(0,1fr)]",
  "features/plugins/PluginsView.tsx: grid-rows-[auto_minmax(0,1fr)]",
  "features/scheduler/SchedulerView.tsx: grid-rows-[auto_minmax(0,1fr)]",
  "features/workflows/WorkflowRevisionHistory.tsx: grid-rows-[auto_minmax(0,1fr)]",
  "features/workflows/WorkflowsView.tsx: grid-rows-[minmax(0,1fr)_minmax(0,1fr)]",
  "features/workflows/WorkflowsView.tsx: grid-rows-[minmax(0,1fr)]",
  "features/workflows/WorkflowsView.tsx: grid-rows-[auto_minmax(0,1fr)]",
]);

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "node_modules" ? [] : sourceFiles(full);
    return /\.tsx$/.test(entry.name) && !entry.name.includes(".test.") ? [full] : [];
  });
}

/** 去掉注释 —— 免得棘轮被「注释里提到 grid-rows」喂饱(这个仓库出过空棘轮)。 */
function strip(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

/**
 * 剥掉变体前缀,取出真正的工具类。
 *
 * `max-[880px]:grid-rows-[...]` 说的还是这个元素,要看;`[&>div]:grid-rows-[...]` 说的是
 * **子元素**,这个元素自己没有行轴声明,不该被这条规则拦下。所以带 `&` 的变体直接跳过。
 */
function utility(token: string): string | null {
  let depth = 0;
  let cut = -1;
  for (let i = 0; i < token.length; i += 1) {
    const ch = token[i];
    if (ch === "[" || ch === "(") depth += 1;
    else if (ch === "]" || ch === ")") depth -= 1;
    else if (ch === ":" && depth === 0) cut = i;
  }
  const variants = token.slice(0, Math.max(cut, 0));
  if (variants.includes("&")) return null;
  return token.slice(cut + 1);
}

interface Hit {
  file: string;
  line: number;
  token: string;
}

/**
 * 一个字符串字面量 = 一次 className 片段。`cn()` 的多个参数各算各的:它们可能来自不同分支,
 * 静态看不出会不会拼在一起,分开看是保守的那一边。
 */
function findHits(): Hit[] {
  const hits: Hit[] = [];
  for (const path of sourceFiles(SRC)) {
    const code = strip(readFileSync(path, "utf8"));
    code.split("\n").forEach((line, index) => {
      for (const literal of line.match(/(["'`])(?:(?!\1)[\s\S])*\1/g) ?? []) {
        const tokens = literal.slice(1, -1).split(/\s+/).map(utility);
        const rows = tokens.find((t) => t?.startsWith("grid-rows-[") && t.includes("minmax(0,"));
        if (!rows) continue;
        if (tokens.some((t) => t?.startsWith("grid-cols-"))) continue;
        hits.push({ file: relative(SRC, path), line: index + 1, token: rows });
      }
    });
  }
  return hits;
}

describe("grid 的两个轴", () => {
  it("锁了行轴就得一起锁列轴", () => {
    const offenders = findHits()
      .map((hit) => `${hit.file}: ${hit.token}`)
      .filter((key) => !GRANDFATHERED.has(key));
    expect(offenders, "补 grid-cols-[minmax(0,1fr)],或给会撑宽的那个子项加 min-w-0").toEqual([]);
  });

  it("存量清单只减不增", () => {
    const live = new Set(findHits().map((hit) => `${hit.file}: ${hit.token}`));
    const stale = [...GRANDFATHERED].filter((key) => !live.has(key));
    expect(stale, "已经修好了,从 GRANDFATHERED 删掉这几行").toEqual([]);
  });
});
