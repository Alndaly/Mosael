/**
 * 截断的字悬停看得到全文:截断一律走 `Truncate`。
 *
 * 列表里的长名字、文件名、网址、工作流名被 `truncate` 截成省略号之后,此前大多数地方就再也
 * 看不全了 —— 有的补了原生 `title`(停一秒多、不管截没截都出),更多的什么都没补。`Truncate`
 * 只在**真被截断**时出说明,说明里是全文;全文一直在 DOM 里,读屏不受影响。
 *
 * 认法:功能代码里,原生标签的 className 里出现 `truncate` 或 `line-clamp-N`,就是自己截了字却
 * 没给全文。换成 `<Truncate>`(多行用 `lines`,别的标签用 `as`)。共用组件(components/ui)自己
 * 实现这件事,不在范围里。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { describe, expect, it } from "vitest";

import { classText, openTags, readSource, tsxSources } from "./jsxSource";

const OWNERS = ["components/ui/"];

/** 存量:只减不增。`文件` → 还剩几处。 */
const STOCK: Record<string, number> = {};

const CLIPPING = /(?:^|\s)(?:[\w-]+:)*(truncate|line-clamp-\d)(?=\s|$)/;

function offenders(): Map<string, string[]> {
  const found = new Map<string, string[]>();
  for (const file of tsxSources()) {
    if (OWNERS.some((owner) => file.startsWith(owner))) continue;
    const code = readSource(file);
    for (const tag of openTags(code)) {
      if (!/^[a-z]/.test(tag.tag)) continue;
      const clip = CLIPPING.exec(classText(tag.attrs.get("className")));
      if (clip) found.set(file, [...(found.get(file) ?? []), `${tag.line}: <${tag.tag} className="…${clip[1]}…">`]);
    }
  }
  return found;
}

describe("截断的字悬停看得到全文", () => {
  const found = offenders();

  it("没有新增的自己截断的字", () => {
    const grown = [...found].filter(([file, list]) => list.length > (STOCK[file] ?? 0)).map(([file, list]) => `${file}\n    ${list.join("\n    ")}`);
    expect(grown, "用 @/components/ui/truncate 的 Truncate(见本文件开头)").toEqual([]);
  });

  it("存量清单没有过时的条目 —— 改好了就把它从清单里删掉", () => {
    const stale = Object.entries(STOCK).filter(([file, count]) => (found.get(file)?.length ?? 0) < count).map(([file]) => file);
    expect(stale).toEqual([]);
  });
});
