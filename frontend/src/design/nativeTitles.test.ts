/**
 * 悬停说明不用原生 `title`。
 *
 * 原生 `title` 要停一秒多才出、样式是系统的、深色下不跟主题,一排图标按钮上等于没有;它还不管
 * 字放不放得下都出 —— 短名字悬停再念一遍是噪音。全应用一度有 400 多处,各写各的。
 *
 * 换成什么:
 * - 只有图标的按钮 → `IconButton`(名字只写一次,同时是 aria-label 和悬停说明;快捷键、禁用原因
 *   都在里面)。
 * - 文字按钮、标签上的补充说明、点不了的原因 → `Hint`(`disabledReason` 给禁用的按钮套一层能接住
 *   悬停的壳)。
 * - 会被截断的名字、文件名、网址 → `Truncate`(真被截断了才出,说明里是全文)。
 *
 * 认的是**写法**:小写的原生标签上写 `title=`,以及把属性原样交给 DOM 的那几个基础组件
 * (Button、SelectTrigger……)上写 `title=`。`<iframe title>` 是给辅助技术的名字(它没有别的
 * 办法有名字),不是悬停说明,留着。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { describe, expect, it } from "vitest";

import { openTags, readSource, tsxSources } from "./jsxSource";

/** 原生标签里 title 不是悬停说明、该留着的。 */
const KEEP_ON = new Set(["iframe"]);

/** 把属性原样交给 DOM 的基础组件:在它们上面写 title 就是原生 title。 */
const PASS_THROUGH = new Set([
  "Button", "SelectTrigger", "SelectItem", "Badge", "Input", "Textarea", "Label", "Checkbox", "Switch",
  "TabsTrigger", "PopoverTrigger", "TooltipTrigger", "CollapsibleTrigger", "DialogTrigger", "ContextMenuTrigger",
  "ContextMenuItem", "CommandItem", "Kbd", "MenuItem",
]);

/** 存量:只减不增。`文件` → 还剩几处。 */
const STOCK: Record<string, number> = {};

function nativeTitles(): Map<string, number> {
  const found = new Map<string, number>();
  for (const file of tsxSources()) {
    const code = readSource(file);
    for (const tag of openTags(code)) {
      if (!tag.attrs.has("title")) continue;
      const native = /^[a-z]/.test(tag.tag) ? !KEEP_ON.has(tag.tag) : PASS_THROUGH.has(tag.tag);
      if (native) found.set(file, (found.get(file) ?? 0) + 1);
    }
  }
  return found;
}

describe("悬停说明不用原生 title", () => {
  const found = nativeTitles();

  it("没有新增的原生 title", () => {
    const grown = [...found].filter(([file, count]) => count > (STOCK[file] ?? 0)).map(([file, count]) => `${file}: ${count}`);
    expect(grown, "用 IconButton / Hint / Truncate(见本文件开头)").toEqual([]);
  });

  it("存量清单没有过时的条目 —— 改好了就把它从清单里删掉", () => {
    const stale = Object.entries(STOCK).filter(([file, count]) => (found.get(file) ?? 0) < count).map(([file]) => file);
    expect(stale).toEqual([]);
  });
});
