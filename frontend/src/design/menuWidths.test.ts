/**
 * 菜单和选值下拉的宽度只在共用组件里定,调用方不写。
 *
 * 此前每个菜单自己挑一个定宽:`w-44`、`w-48`、`w-[200px]`……中文刚好放得下的,英文就被截掉
 * 半句(笔记「插入▾」的「插入图片(也可粘贴或拖入)」在 192px 里只剩前半截,用户截图);另一些
 * 下拉没有上限,一个 checkpoint 文件名把菜单撑成半屏宽,调用方再各自补 `max-w-[min(360px,…)]`、
 * `max-w-none` 去压或放。同一种东西七八种宽度。
 *
 * 规则在 components/ui/floating.ts:MENU_WIDTH(动作菜单、右键菜单)、SELECT_CONTENT_WIDTH、
 * SEARCHABLE_CONTENT_WIDTH(选值下拉)。菜单项里静态文案折行、动态长值截断,见 MenuItemBody。
 *
 * 认法:
 * - SelectContent / ContextMenuContent / ContextMenuSubContent / MenuContent 的 className,
 *   OptionPicker / SearchableSelect / Combobox 的 contentClassName,里面不出现宽度类。
 * - 点按钮弹出的菜单用 MenuContent,不在 PopoverContent 上自己挂 `role="menu"`。
 * - 菜单行的外观走 MenuItem / MenuItemBody,不在功能代码里直接拿 MENU_ITEM / ACTION_MENU 拼。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { describe, expect, it } from "vitest";

import { classText, openTags, readSource, tsxSources } from "./jsxSource";

const OWNERS = ["components/ui/"];

const MENU_SURFACES: Record<string, string> = {
  SelectContent: "className",
  ContextMenuContent: "className",
  ContextMenuSubContent: "className",
  MenuContent: "className",
  OptionPicker: "contentClassName",
  SearchableSelect: "contentClassName",
  Combobox: "contentClassName",
};

/** 存量:只减不增。`文件` → 还剩几处。 */
const STOCK: Record<string, number> = {};

const WIDTH_CLASS = /(?:^|\s)(?:[\w-]+:)*(?:min-|max-)?w-\S+/;

function offenders(): Map<string, string[]> {
  const found = new Map<string, string[]>();
  const add = (file: string, what: string) => found.set(file, [...(found.get(file) ?? []), what]);
  for (const file of tsxSources()) {
    if (OWNERS.some((owner) => file.startsWith(owner))) continue;
    const code = readSource(file);
    for (const tag of openTags(code)) {
      const prop = MENU_SURFACES[tag.tag];
      if (prop) {
        const width = WIDTH_CLASS.exec(classText(tag.attrs.get(prop)));
        if (width) add(file, `${tag.line}: <${tag.tag} ${prop}> 里写了宽度 ${width[0].trim()}`);
      }
      if (tag.tag === "PopoverContent" && tag.attrs.get("role") === '"menu"') {
        add(file, `${tag.line}: PopoverContent role="menu" → MenuContent`);
      }
    }
    for (const match of code.matchAll(/\b(ACTION_MENU|MENU_ITEM)\b(?!_)/g)) {
      add(file, `${code.slice(0, match.index).split("\n").length}: ${match[1]} → MenuItem / MenuItemBody`);
    }
  }
  return found;
}

describe("菜单宽度只在共用组件里定", () => {
  const found = offenders();

  it("没有新增的自定宽度菜单", () => {
    const grown = [...found].filter(([file, list]) => list.length > (STOCK[file] ?? 0)).map(([file, list]) => `${file}\n    ${list.join("\n    ")}`);
    expect(grown, "宽度规则在 components/ui/floating.ts;菜单用 MenuContent / MenuItem(见本文件开头)").toEqual([]);
  });

  it("存量清单没有过时的条目 —— 改好了就把它从清单里删掉", () => {
    const stale = Object.entries(STOCK).filter(([file, count]) => (found.get(file)?.length ?? 0) < count).map(([file]) => file);
    expect(stale).toEqual([]);
  });
});
