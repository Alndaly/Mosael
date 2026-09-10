/**
 * 同一行里的控件要一样高。
 *
 * 这条拦的是「一行里混了两个刻度」。最常见的两种长相:
 *
 *     <Input /> <Button size="sm">    输入框 40px、按钮 32px,按钮贴着输入框矮一截
 *     .scene-segment 配 .scene-labeled-tool   外壳 3px 内距 + 1px 边框把 30px 的按钮
 *                                             撑成 38px,而旁边的工具是 32px
 *
 * 后一种是重点:**高度是算出来的,不是写出来的**。作者只给里面的按钮写了 30px,没有人
 * 在任何地方写下 38 —— 于是 grep 找不到它,评审也看不出来,只有渲染出来才露馅。所以这条
 * 棘轮不比字符串,它按 `box-sizing: border-box` 把内距、边框、行高**算**成一个高度,
 * 再比同一行的兄弟节点。
 *
 * ## 它看得见什么、看不见什么
 *
 * 看得见:写了 `h-N`/`size-N` 的、走 `<Button size>` 的、CSS 里定了 height 的、以及
 * 由内距 + 边框 + 行高能算出来的。组件把 class 藏在自己内部(`<Tool/>` 渲染成
 * `.scene-tool`)时会顺着组件名找到它的根元素 class。一组控件嵌在中间的 div 里时,
 * 这一层折算成「里面最高的那个」再和外层的兄弟比。
 *
 * 看不见:高度来自内容本身(一段会换行的文字、一张图),或者 class 是运行时拼出来的。
 * 那些行这里判不了,只能靠眼睛 —— 所以这条棘轮是**下限**,不是「全绿就没有参差」。
 *
 * 走 portal 的东西(Popover/Dialog/…)不占行内空间,不参与比较。
 *
 * 存量冻结在 GRANDFATHERED,每一条都写清楚为什么它该不一样;清单只减不增。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");

/**
 * 存量:同一行里**故意**不同高的地方,记成 `文件: 高度/高度`(不带行号 —— 挪一行代码就要
 * 改清单的话,清单就没人愿意维护了;和 `buttonScale.test.ts`、`gridAxes.test.ts` 同一套键)。
 */
const GRANDFATHERED = new Map<string, string>([
  // 圆形发送键是这一行的主操作,故意比左边那排 28px 的工具大一圈。
  ["components/agent/CanvasAgentChat.tsx: 28/36", "发送键是主操作,故意更大"],
  ["features/ai-studio/AiStudio.tsx: 28/36", "同上"],
  ["features/ai-studio/ChatWorkspace.tsx: 28/36", "同上"],
  // 进度条/滑杆:轨道和滑块本来就不该和按钮一样高。
  ["components/app/MediaPreviewPlayer.tsx: 16/32", "进度条不是控件,是轨道"],
  ["components/ui/slider.tsx: 6/16", "滑杆的轨道与滑块"],
  ["components/ui/command.tsx: 16/40", "放大镜图标在输入框内部"],
  // 画布上的小圆工具条:配色圆点比图标按钮小是有意的。
  ["features/boards/BoardCanvas.tsx: 24/28", "配色圆点比图标按钮小"],
]);

/** `box-sizing: border-box` 是全局的(design/tokens.css),所以写了 height 就是最终高度。 */
const LINE_HEIGHT = 1.5;
const FONT = new Map([
  ["--text-ui-2xs", 11], ["--text-ui-xs", 12], ["--text-ui-sm", 14],
  ["--text-ui-md", 16], ["--text-ui-lg", 18],
]);
const BUTTON_SIZE = new Map([
  ["default", 40], ["lg", 44], ["icon", 36],
  ["sm", 32], ["icon-sm", 32], ["xs", 28], ["icon-xs", 28],
]);
/** 走 portal 渲染,不占所在行的空间。 */
const PORTALED = new Set([
  "Popover", "PopoverContent", "Dialog", "DialogContent", "ModalShell", "Tooltip",
  "TooltipContent", "SelectContent", "DropdownMenu", "DropdownMenuContent",
  "AlertDialog", "Sheet",
]);
/** 文字节点,不是控件。 */
const TEXT = new Set(["span", "p", "strong", "em", "small", "code", "Skeleton", "svg"]);
/**
 * **自己把 children 摆成一行的组件。**
 *
 * 判据本来是"父元素身上写着 flex + items-center" —— 而 SettingsRow 的那一行写在组件里
 * (`ui.tsx` 的控件槽),调用点只看得见 `<SettingsRow>`。于是设置页的每一行控件对这条棘轮
 * 都是隐形的:一个 40px 的输入框旁边配 32px 的保存键,一直没人拦。
 */
const ROW_COMPONENT = new Set(["SettingsRow", "SettingsField"]);

function files(dir: string, ext: RegExp): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "node_modules" ? [] : files(full, ext);
    return ext.test(entry.name) ? [full] : [];
  });
}

type Decls = Record<string, string>;
const vars = new Map<string, string>();
const decls = new Map<string, Decls>();
const rowClass = new Set<string>();
/** `.row > button { height }` —— 整行被一条规则钉住了,不必再比。 */
const pinned = new Set<string>();

function record(key: string, body: string) {
  const at = decls.get(key) ?? {};
  for (const one of body.split(";")) {
    const colon = one.indexOf(":");
    if (colon > 0) at[one.slice(0, colon).trim()] = one.slice(colon + 1).trim();
  }
  decls.set(key, at);
}

for (const file of files(SRC, /\.css$/)) {
  const css = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  for (const rule of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const [, selector, body] = rule;
    if (selector.trim().startsWith("@")) continue;
    for (const v of body.matchAll(/(--[\w-]+):\s*([^;]+)/g))
      if (!vars.has(v[1])) vars.set(v[1], v[2].trim());
    for (const one of selector.split(",").map((s) => s.trim())) {
      if (/^\.[\w-]+$/.test(one)) {
        record(one.slice(1), body);
        if (/display:\s*(inline-)?flex/.test(body)
          && /align-items:\s*(center|stretch|baseline)/.test(body)
          && !/flex-direction:\s*column/.test(body)) rowClass.add(one.slice(1));
      }
      const parent = one.match(/^\.([\w-]+)\s*>\s*\S/);
      if (parent && /(?:^|;)\s*(?:min-)?height:/.test(body)) pinned.add(parent[1]);
      const nested = one.match(/^\.[\w-]+\s*>?\s+\.([\w-]+)$/);
      if (nested) record(nested[1], body);
      const element = one.match(/^\.([\w-]+)\s*>?\s+([a-z]+|\[role="[\w-]+"\])$/);
      if (element) record(`${element[1]} ${element[2]}`, body);
    }
  }
}

function pixels(value: string | undefined): number | null {
  if (!value) return null;
  const ref = value.trim().match(/^var\((--[\w-]+)/);
  if (ref) return pixels(vars.get(ref[1]));
  const px = value.trim().match(/^(\d+(?:\.\d+)?)px$/);
  return px ? Number(px[1]) : null;
}
function blockPadding(at: Decls): [number, number] | null {
  const all = at.padding;
  if (all) {
    const parts = all.trim().split(/\s+/).map(pixels);
    if (!parts.every((p) => p != null)) return null;
    return parts.length === 1 ? [parts[0]!, parts[0]!] : [parts[0]!, parts[2] ?? parts[0]!];
  }
  const top = pixels(at["padding-top"] ?? at["padding-block-start"]);
  const bottom = pixels(at["padding-bottom"] ?? at["padding-block-end"]);
  return top != null || bottom != null ? [top ?? 0, bottom ?? 0] : null;
}
function borderWidth(at: Decls): number {
  const border = at.border ?? at["border-width"];
  const px = border?.match(/(\d+)px/);
  return px ? Number(px[1]) * 2 : 0;
}
function height(cls: string): number | null {
  const at = decls.get(cls);
  if (!at) return null;
  const fixed = pixels(at.height) ?? pixels(at["min-height"]);
  if (fixed != null) return fixed;
  const inner = [...decls.keys()]
    .filter((k) => k.startsWith(`${cls} `))
    .map((k) => pixels(decls.get(k)!.height))
    .filter((v): v is number => v != null);
  const padding = blockPadding(at);
  if (inner.length && padding) return Math.max(...inner) + padding[0] + padding[1] + borderWidth(at);
  if (!padding) return null;
  const token = at["font-size"]?.match(/var\((--[\w-]+)/);
  const size = token ? (FONT.get(token[1]) ?? 14) : (pixels(at["font-size"] ?? "") ?? 14);
  return padding[0] + padding[1] + borderWidth(at) + Math.round(size * LINE_HEIGHT);
}

/** `<Tool/>` 这类把 class 藏在自己内部的组件:找到它渲染的根元素 class。 */
const componentClass = new Map<string, string>();
const sources = files(SRC, /\.tsx$/);
for (const file of sources) {
  const src = readFileSync(file, "utf8");
  for (const m of src.matchAll(
    /(?:export\s+)?function\s+([A-Z]\w*)\s*\([\s\S]{0,900}?\breturn\s*\(?\s*<(?:[A-Za-z][\w.]*)\s[^>]*?className="([\w\s-]+)"/g,
  )) if (!componentClass.has(m[1])) componentClass.set(m[1], m[2]);
}

const classOf = (attrs: string) => {
  const m = attrs.match(/className=(?:"([^"]*)"|\{`([^`]*)`|\{cn\(([\s\S]*?)\)\s*\}|\{"([^"]*)")/);
  return m ? (m[1] ?? m[2] ?? m[3] ?? m[4] ?? "") : "";
};
function measure(tag: string, attrs: string, parentClass: string | undefined): number | null {
  for (const name of (parentClass ?? "").split(/\s+/).filter(Boolean)) {
    const scoped = height(`${name} ${tag}`)
      ?? (tag === "Pick" || tag === "SelectTrigger" ? height(`${name} [role="combobox"]`) : null);
    if (scoped != null) return scoped;
  }
  const cls = classOf(attrs);
  const utility = /\b(?:min-)?h-(\d+(?:\.5)?)\b/.exec(cls)?.[1] ?? /\bsize-(\d+(?:\.5)?)\b/.exec(cls)?.[1];
  if (utility) return Number.parseFloat(utility) * 4;
  for (const name of cls.split(/\s+/)) {
    const own = height(name);
    if (own != null) return own;
  }
  if (tag === "Button") return BUTTON_SIZE.get(attrs.match(/size="([^"]+)"/)?.[1] ?? "default") ?? 40;
  if (tag === "Input" || tag === "SelectTrigger" || tag === "Pick") return 40;
  for (const name of (componentClass.get(tag) ?? "").split(/\s+/).filter(Boolean)) {
    const own = height(name);
    if (own != null) return own;
  }
  return null;
}
function rowOf(attrs: string, tag?: string): { cls?: string } | null {
  if (tag && ROW_COMPONENT.has(tag)) return {};
  const cls = classOf(attrs);
  if (/\bflex\b/.test(cls) && !/\bflex-col\b/.test(cls) && /\bitems-(center|stretch|baseline)\b/.test(cls))
    return {};
  const named = cls.split(/\s+/).find((n) => rowClass.has(n));
  return named ? { cls: named } : null;
}

const TAG = /<(\/?)([A-Za-z][\w.]*)((?:"[^"]*"|'[^']*'|\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\}|[^>"'{])*?)(\/?)>/g;
/** 一行里最高与最矮相差这么多才算参差 —— 1-2px 的差是字体度量,不是刻度选错。 */
const TOLERANCE = 3;

type Frame = { tag: string; cls: string; row: ReturnType<typeof rowOf>; kids: number[]; self: number | null; pad: number };

function scan(file: string) {
  const src = readFileSync(file, "utf8");
  const found: { heights: number[] }[] = [];
  const stack: Frame[] = [];
  const close = (frame: Frame): number | null => {
    if (frame.row && !(frame.cls && [...frame.cls.split(/\s+/)].some((n) => pinned.has(n)))) {
      const spread = frame.kids.length > 1 ? Math.max(...frame.kids) - Math.min(...frame.kids) : 0;
      if (spread >= TOLERANCE) found.push({ heights: [...new Set(frame.kids)].sort((a, b) => a - b) });
    }
    if (frame.self != null) return frame.self;
    return frame.kids.length ? Math.max(...frame.kids) + frame.pad : null;
  };
  let m: RegExpExecArray | null;
  TAG.lastIndex = 0;
  while ((m = TAG.exec(src))) {
    const [, closing, tag, attrs, self] = m;
    if (closing) {
      const frame = stack.pop();
      if (!frame) continue;
      const outer = close(frame);
      const up = stack[stack.length - 1];
      if (up?.row && outer != null && !TEXT.has(frame.tag) && !PORTALED.has(frame.tag)) up.kids.push(outer);
      continue;
    }
    const parent = stack[stack.length - 1];
    const own = measure(tag, attrs, parent?.cls);
    if (self) {
      if (parent?.row && own != null && !TEXT.has(tag) && !PORTALED.has(tag)) parent.kids.push(own);
      continue;
    }
    const cls = classOf(attrs);
    const at = decls.get(cls.split(/\s+/).find((n) => decls.has(n)) ?? "");
    const padding = at ? blockPadding(at) : null;
    stack.push({ tag, cls, row: rowOf(attrs, tag), kids: [], self: own, pad: padding ? padding[0] + padding[1] : 0 });
  }
  while (stack.length) {
    const frame = stack.pop()!;
    const outer = close(frame);
    const up = stack[stack.length - 1];
    if (up?.row && outer != null && !TEXT.has(frame.tag) && !PORTALED.has(frame.tag)) up.kids.push(outer);
  }
  return found;
}

describe("同一行的控件同高", () => {
  const mixed = new Map<string, number[][]>();
  for (const file of sources) {
    for (const row of scan(file)) {
      const key = `${relative(SRC, file).replaceAll("\\", "/")}: ${row.heights.join("/")}`;
      mixed.set(key, [...(mixed.get(key) ?? []), row.heights]);
    }
  }

  it("没有新的参差", () => {
    const fresh = [...mixed.keys()].filter((k) => !GRANDFATHERED.has(k)).sort();
    expect(fresh, [
      "这一行里的控件高度对不上。要么把它们收到同一档,要么 —— 如果这个差是有意的 ——",
      "写进 GRANDFATHERED 并说明理由。档位见 components/ui/button.tsx 的 buttonVariants。",
    ].join("\n")).toEqual([]);
  });

  it("清单只减不增", () => {
    const stale = [...GRANDFATHERED.keys()].filter((k) => !mixed.has(k)).sort();
    expect(stale, "这些行已经对齐了,从 GRANDFATHERED 里删掉,棘轮就收紧一格。").toEqual([]);
  });
});
