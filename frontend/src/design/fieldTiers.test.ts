/**
 * 同一个容器里的字段同一档。
 *
 * 维护者截图:AI Studio 右栏「模型」下拉是 sm(32),旁边「音色」是 md(40)—— 同一个面板里两种框,哪个都说得过去,
 * 放在一起就是「这排东西没对齐」。规格:一个容器一个档(docs/DESIGN_LANGUAGE.md「三条总规则」)。
 *
 * 认法(静态):容器 = 表单(`<form>`)、对话框(`ModalShell`、`DialogContent`、`AlertDialogContent`、`SheetContent`)、
 * 弹出层(`PopoverContent`)、侧栏(`<aside>`)、设置页的一节(`SettingsGroup`、`SettingsBlock`)。每个字段(输入框、
 * 下拉触发器、选项选择器、可搜索下拉、组合框、时间选择)归到**最里面**那个容器;一个容器里的字段 `size` 不止一种就算。
 * 没写 size 是 md;`size={…}` 是算出来的,这里判不了 —— 那几处靠 DOM 一致性测试(`src/test/fieldTier.ts`)。
 *
 * 存量按文件冻结,只减不增。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { describe, expect, it } from "vitest";

import { childrenOf, openTags, readSource, tsxSources } from "@/design/jsxSource";

const CONTAINERS = new Set([
  "form",
  "aside",
  "ModalShell",
  "DialogContent",
  "AlertDialogContent",
  "SheetContent",
  "PopoverContent",
  "SettingsGroup",
  "SettingsBlock",
]);
const FIELDS = new Set(["Input", "SearchInput", "SelectTrigger", "OptionPicker", "SearchableSelect", "Combobox", "TimePicker"]);
const OWNERS = ["components/ui/", "dev/"];

/** 存量:`文件` → 几个容器里混了档。只减不增。 */
const STOCK: Record<string, number> = {};

type Span = { tag: string; line: number; from: number; to: number };

/** 一份源码里混了档的容器(`行: <容器> 里有 md / sm`)。 */
export function mixedIn(code: string): string[] {
  const tags = openTags(code);
  const spans: Span[] = [];
  for (const tag of tags) {
    if (!CONTAINERS.has(tag.tag) || tag.selfClosing) continue;
    const inner = childrenOf(code, tag);
    if (inner !== null) spans.push({ tag: tag.tag, line: tag.line, from: tag.end, to: tag.end + inner.length });
  }
  const tiers = new Map<Span, Set<string>>();
  for (const tag of tags) {
    if (!FIELDS.has(tag.tag)) continue;
    const size = tag.attrs.get("size");
    if (size !== undefined && !/^"(xs|sm|md)"$/.test(size)) continue; // 算出来的,判不了
    const tier = size === undefined ? "md" : size.slice(1, -1);
    const owner = spans.filter((span) => span.from <= tag.start && tag.start < span.to).sort((a, b) => b.from - a.from)[0];
    if (!owner) continue;
    tiers.set(owner, new Set([...(tiers.get(owner) ?? []), tier]));
  }
  return [...tiers].filter(([, set]) => set.size > 1).map(([span, set]) => `${span.line}: <${span.tag}> 里有 ${[...set].sort().join(" / ")}`);
}

export function mixedContainers(): Map<string, string[]> {
  const found = new Map<string, string[]>();
  for (const file of tsxSources()) {
    if (OWNERS.some((owner) => file.startsWith(owner))) continue;
    const mixed = mixedIn(readSource(file));
    if (mixed.length > 0) found.set(file, mixed);
  }
  return found;
}

describe("同一个容器里的字段同一档", () => {
  const found = mixedContainers();

  it("没有新增的混档容器", () => {
    const grown = [...found]
      .filter(([file, list]) => list.length > (STOCK[file] ?? 0))
      .map(([file, list]) => `${file}(存量 ${STOCK[file] ?? 0})\n    ${list.join("\n    ")}`);
    expect(grown, "一个容器一个档:表单、对话框、侧栏面板 md,工具条按它那一档(docs/DESIGN_LANGUAGE.md)").toEqual([]);
  });

  it("认得出:字段归到最里面的容器;算出来的 size 不判", () => {
    const code = [
      "<ModalShell>",
      '  <Input size="sm" />',
      "  <form>",
      "    <Input />",
      "    <SelectTrigger />",
      "  </form>",
      "  <aside>",
      "    <Input />",
      '    <OptionPicker size="xs" />',
      "    <TimePicker size={tier} />",
      "  </aside>",
      "</ModalShell>",
    ].join("\n");
    expect(mixedIn(code)).toEqual(["7: <aside> 里有 md / xs"]);
  });

  it("存量清单没有过时的条目", () => {
    const stale = Object.entries(STOCK)
      .filter(([file, count]) => (found.get(file)?.length ?? 0) < count)
      .map(([file, count]) => `${file}: 清单 ${count},现在 ${found.get(file)?.length ?? 0}`);
    expect(stale).toEqual([]);
  });
});
