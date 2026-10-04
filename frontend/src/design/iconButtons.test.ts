/**
 * 只有图标的按钮必须有名字:读屏念的 `aria-label`,和悬停时看得见的说明。
 *
 * 两样缺一样都是真实的坏法:没有 aria-label,读屏只念「按钮」;没有悬停说明,一排图标只能
 * 挨个点开猜(原生 `title` 不算 —— 见 nativeTitles.test.ts)。两样分开写又会写岔:改了一处名字,
 * 另一处还是旧的。所以只认一种写法 —— `IconButton`,名字只写一次。
 *
 * 认法:
 * - `<Button size="icon…">` 一律换成 `<IconButton>`。
 * - 原生 `<button>`,子内容只有图标(大写开头的自闭合组件、`<svg>`、`{icon}`、`<span>` 里只包一个
 *   图标、`cond ? <A/> : <B/>`)的,换成 `<IconButton unstyled>`;或者确实要自己套 `Hint` 的
 *   (触发器链 `Hint > PopoverTrigger asChild > button`),那颗按钮要有 aria-label。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { describe, expect, it } from "vitest";

import { childrenOf, openTags, readSource, skipBraces, tsxSources, type OpenTag } from "./jsxSource";

/** 共用组件自己实现这些规矩,不在检查范围里。 */
const OWNERS = ["components/ui/"];

/** 存量:只减不增。`文件` → 还剩几处。 */
const STOCK: Record<string, number> = {};

/** 套在按钮外面、把属性原样转给它的触发器(`asChild`)—— 往外再找一层看是不是 Hint。 */
const PASS_THROUGH_TRIGGERS = new Set([
  "PopoverTrigger", "PopoverClose", "PopoverAnchor", "CollapsibleTrigger", "DialogTrigger", "DialogClose",
  "AlertDialogTrigger", "AlertDialogCancel", "AlertDialogAction", "ContextMenuTrigger", "SheetTrigger", "SheetClose",
]);

/**
 * 哪些标签算图标:从 lucide-react 引进来的组件、名字以 Icon 结尾的(`ThemeIcon`、`action.icon`)、
 * `<svg>` / `<img>`。**不是「大写开头的组件」一律算** —— 那样一张卡片(`<PublishCard/>`)、一行
 * 菜单(`<MenuItemBody/>`)也成了图标。
 */
function isIconTag(tag: string, icons: ReadonlySet<string>): boolean {
  return icons.has(tag) || /(?:^|\.)\w*[iI]con$/.test(tag) || tag === "svg" || tag === "img";
}

/** 这个文件从 lucide-react 引进来的名字(含 `as` 改的名)。 */
export function lucideNames(code: string): Set<string> {
  const names = new Set<string>();
  for (const match of code.matchAll(/import\s*\{([^}]*)\}\s*from\s*["']lucide-react["']/g)) {
    for (const part of match[1].split(",")) {
      const name = part.trim().replace(/^type\s+/, "").split(/\s+as\s+/).pop()?.trim();
      if (name) names.add(name);
    }
  }
  return names;
}

/** 子内容是不是只有图标。 */
export function iconOnly(children: string, icons: ReadonlySet<string>): boolean {
  let rest = children.trim();
  // `<span …><Icon/></span>`:只包一个图标的外壳。
  const shell = /^<span\b[^>]*>([\s\S]*)<\/span>$/.exec(rest);
  if (shell && !/<span\b/.test(shell[1])) rest = shell[1].trim();
  let sawIcon = false;
  let i = 0;
  while (i < rest.length) {
    const c = rest[i];
    if (/\s/.test(c)) {
      i += 1;
    } else if (c === "<") {
      const piece = rest.slice(i);
      const [tag] = openTags(piece);
      if (!tag || tag.start !== 0 || !isIconTag(tag.tag, icons)) return false;
      if (tag.selfClosing) {
        i += tag.end;
      } else {
        const inner = tag.tag === "svg" ? childrenOf(piece, tag) : null;
        if (inner === null) return false;
        i += tag.end + inner.length + "</svg>".length;
      }
      sawIcon = true;
    } else if (c === "{") {
      const end = skipBraces(rest, i);
      if (!iconExpression(rest.slice(i + 1, end - 1).trim(), icons)) return false;
      sawIcon = true;
      i = end;
    } else {
      return false;
    }
  }
  return sawIcon;
}

/** `{icon}`、`{item.icon}`、`{busy ? <Loader2/> : <Send/>}`、`{open && <X/>}`:只有图标和条件。 */
function iconExpression(expr: string, icons: ReadonlySet<string>): boolean {
  if (/^[\w.]*[iI]con$/.test(expr)) return true;
  if (!expr.includes("<")) return false;
  const tags = openTags(expr);
  let leftover = expr;
  for (const tag of [...tags].reverse()) {
    if (!isIconTag(tag.tag, icons) || !tag.selfClosing) return false;
    leftover = leftover.slice(0, tag.start) + leftover.slice(tag.end);
  }
  return tags.length > 0 && /^[\w.!?:&|()\s]*$/.test(leftover);
}

function hintedBy(tags: OpenTag[], code: string, button: OpenTag): boolean {
  let at = button.start;
  for (;;) {
    const before = code.slice(0, at).trimEnd();
    if (!before.endsWith(">")) return false;
    const parent = tags.find((tag) => tag.end === before.length && !tag.selfClosing);
    if (!parent) return false;
    if (parent.tag === "Hint" || parent.tag === "TooltipTrigger") return true;
    if (!PASS_THROUGH_TRIGGERS.has(parent.tag) || !parent.attrs.has("asChild")) return false;
    at = parent.start;
  }
}

function offenders(): Map<string, string[]> {
  const found = new Map<string, string[]>();
  const add = (file: string, what: string) => found.set(file, [...(found.get(file) ?? []), what]);
  for (const file of tsxSources()) {
    if (OWNERS.some((owner) => file.startsWith(owner))) continue;
    const code = readSource(file);
    const tags = openTags(code);
    const icons = lucideNames(code);
    for (const tag of tags) {
      if (tag.tag === "Button" && /^["{]["'`]?icon(-sm|-xs)?["'`]?\}?"?$/.test(tag.attrs.get("size") ?? "")) {
        add(file, `${tag.line}: <Button size=icon…> → <IconButton>`);
        continue;
      }
      if (tag.tag !== "button") continue;
      const children = childrenOf(code, tag);
      if (children === null || !iconOnly(children, icons)) continue;
      if (hintedBy(tags, code, tag) && tag.attrs.has("aria-label")) continue;
      add(file, `${tag.line}: 只有图标的 <button> → <IconButton unstyled>`);
    }
  }
  return found;
}

describe("只有图标的按钮有名字、有悬停说明", () => {
  const found = offenders();

  it("没有新增的漏网按钮", () => {
    const grown = [...found].filter(([file, list]) => list.length > (STOCK[file] ?? 0)).map(([file, list]) => `${file}\n    ${list.join("\n    ")}`);
    expect(grown, "用 @/components/ui/icon-button 的 IconButton(见本文件开头)").toEqual([]);
  });

  it("存量清单没有过时的条目 —— 改好了就把它从清单里删掉", () => {
    const stale = Object.entries(STOCK).filter(([file, count]) => (found.get(file)?.length ?? 0) < count).map(([file]) => file);
    expect(stale).toEqual([]);
  });

  it("认法本身:图标、图标外壳、条件图标算;有字的不算", () => {
    const icons = lucideNames(`import { Undo2, Loader2, Boxes, Send, Plus, type LucideIcon, Check as Tick } from "lucide-react";`);
    expect([...icons]).toEqual(["Undo2", "Loader2", "Boxes", "Send", "Plus", "LucideIcon", "Tick"]);
    expect(iconOnly("<Undo2 />", icons)).toBe(true);
    expect(iconOnly(`<Loader2 className="animate-spin" size={14} />`, icons)).toBe(true);
    expect(iconOnly(`<span className="grid"><Boxes size={20} /></span>`, icons)).toBe(true);
    expect(iconOnly("{busy ? <Loader2 /> : <Send />}", icons)).toBe(true);
    expect(iconOnly("<action.icon size={16} />", icons)).toBe(true);
    expect(iconOnly("<ThemeIcon size={15} />", icons)).toBe(true);
    expect(iconOnly("<Tick />", icons)).toBe(true);
    expect(iconOnly("{icon}", icons)).toBe(true);
    expect(iconOnly(`<Plus />{t("add")}`, icons)).toBe(false);
    expect(iconOnly("{label}", icons)).toBe(false);
    expect(iconOnly(`<Plus /><span>{t("insert")}</span>`, icons)).toBe(false);
    expect(iconOnly("<Truncate>{name}</Truncate>", icons)).toBe(false);
    // 卡片、菜单行这类大写开头的组件不是图标。
    expect(iconOnly("<PublishCard task={task} /><SelectionCheck />", icons)).toBe(false);
    expect(iconOnly("<MenuItemBody label={label} />", icons)).toBe(false);
  });
});
