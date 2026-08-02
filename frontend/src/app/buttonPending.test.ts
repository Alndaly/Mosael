/**
 * 结构性约束:**会发请求的按钮必须反映它自己的进行中状态**。
 *
 * 不接的话按钮点下去看起来没反应,于是用户再点一次 —— 而第二次点的往往是一个已经不存在的
 * 对象(那条记录刚被删掉、那条排队消息刚被撤回)。这不是观感问题。
 *
 * 判据(Button 的 `loading` 注释里写的是同一条):点下去会发请求,而且**没有别的即时反馈**。
 * 纯前端的开合/筛选不算;点完立刻关掉弹层、或者当场把界面换掉的,那个变化本身就是反馈。
 *
 * 例外只能出现在 EXEMPT 里,而且要写清楚"它的即时反馈是什么" —— 只减不增,和
 * tests/test_data_ownership_ratchet.py 是同一套棘轮。
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const SRC = path.resolve(__dirname, "..");

/** `<文件:行>` → 为什么不需要 loading。 */
const EXEMPT: Record<string, string> = {
  "features/editor/EditorView.tsx:startExport":
    "点完立刻关掉导出配置弹层,并在任务中心出现一条任务 —— 弹层消失就是那个反馈。",
  "features/editor/TranscriptPanel.tsx:startAsr":
    "自己算了 asrRunning(isPending || 有在跑的 job),按钮内已经换成转圈 + 文案。",
  "features/settings/FeishuSection.tsx:beginScan":
    "接的是同步置起的 scanning 而不是 isPending —— 弹层要在请求发出前就显示加载态。",
};

/** 粗略切出 `<Tag ...>` 开标签:跳过 `=>` 里的 `>`,按花括号深度配对。 */
function openTags(text: string, tag: string): Array<{ index: number; source: string }> {
  const out: Array<{ index: number; source: string }> = [];
  const re = new RegExp(`<${tag}\\b`, "g");
  let match: RegExpExecArray | null;
  while ((match = re.exec(text)) !== null) {
    let i = re.lastIndex;
    let depth = 0;
    while (i < text.length) {
      const c = text[i];
      if (c === "{") depth += 1;
      else if (c === "}") depth -= 1;
      else if (c === ">" && depth === 0 && text[i - 1] !== "=") {
        out.push({ index: match.index, source: text.slice(match.index, i + 1) });
        break;
      }
      i += 1;
    }
  }
  return out;
}

function walk(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return walk(full);
    return entry.isFile() && full.endsWith(".tsx") ? [full] : [];
  });
}

describe("会发请求的按钮都反映进行中状态", () => {
  it("没有新增的漏网按钮", () => {
    const missing: string[] = [];
    for (const file of walk(SRC)) {
      const text = fs.readFileSync(file, "utf8");
      if (!text.includes("useMutation")) continue;
      const rel = path.relative(SRC, file);
      // onClick={handler} 时把那个 handler 的函数体也算进来
      const handlers = new Map<string, string>();
      for (const m of text.matchAll(/const (\w+) = \([^)]*\) => \{(?:[^{}]|\{[^{}]*\})*\}/g)) {
        handlers.set(m[1], m[0]);
      }
      for (const { source } of [...openTags(text, "Button"), ...openTags(text, "button")]) {
        let body = source;
        for (const h of source.matchAll(/onClick=\{(\w+)\}/g)) body += handlers.get(h[1]) ?? "";
        const names = [...body.matchAll(/(\w+)\.mutate(?:Async)?\(/g)].map((m) => m[1]);
        if (names.length === 0) continue;
        // 接了任意一个相关 mutation 的 isPending 就算过关(disabled 与 loading 都数)
        if (names.some((name) => source.includes(`${name}.isPending`))) continue;
        const key = `${rel}:${names[0]}`;
        if (key in EXEMPT) continue;
        missing.push(key);
      }
    }
    expect(missing).toEqual([]);
  });

  it("豁免清单里没有已经过时的条目", () => {
    const live = new Set<string>();
    for (const file of walk(SRC)) {
      const text = fs.readFileSync(file, "utf8");
      if (!text.includes("useMutation")) continue;
      const rel = path.relative(SRC, file);
      for (const m of text.matchAll(/(\w+)\.mutate(?:Async)?\(/g)) live.add(`${rel}:${m[1]}`);
    }
    // 豁免只能减不能增:留着一条指向已删代码的豁免,下一个人会以为那里"故意不接"。
    expect(Object.keys(EXEMPT).filter((key) => !live.has(key))).toEqual([]);
  });
});
