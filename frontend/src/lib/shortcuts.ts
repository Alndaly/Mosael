/**
 * 快捷键:归一、显示,以及**应用已经占用了哪些键**。
 *
 * 这份名单存在的理由只有一个:用户能自己绑键了(画布标记),而绑到一个已经有用的键上,
 * 结果不是"两个都触发",是**其中一个从此不响应** —— 而它看起来就是个 bug,还是个只在
 * 那一台机器上复现、只在那一张画布上复现的 bug。所以配置的时候就要拒绝,并且说清楚是和谁撞了。
 *
 * ## 归一的规则归契约管
 *
 * 后端在保存时用同一套规则查重(`backend/app/domain/markers.py`),而两边归出不同的串时谁都
 * 不报错、只会悄悄错开。所以语料在 `contracts/marker-shortcut-cases.json`,两侧跑同一份。
 *
 * ## 为什么 ⌘ 和 Ctrl 合并成一个 `Mod`
 *
 * 应用里每一处快捷键判的都是 `metaKey || ctrlKey`(macOS 按 ⌘、Windows 按 Ctrl,同一件事)。
 * 分开存的话,同一张画板在两个系统上就会有两套绑定 —— 而画板是跟着工作区走的,不跟着机器走。
 *
 * ## 这份名单不是全集,是**已知会撞的那些**
 *
 * 项目里没有中央快捷键注册表(四十来处各自 `addEventListener("keydown")`),所以这份名单
 * 是照着那些处理器抄出来的。抄漏一个的代价是"某个键绑上去之后不太灵",不是数据损坏 ——
 * 而把它做成注册表要改四十来个文件。先把名单钉住,并用一条测试盯着它别缩水。
 */

import type { MessageKey } from "@/app/messages";

/** 规范形态:`Mod+Alt+Shift+K`。修饰键固定这个顺序,键名字母统一大写。 */
export type Combo = string;

const MODIFIER_ORDER = ["Mod", "Alt", "Shift"] as const;

/** 能绑的功能键。Enter / Escape / Tab / Space / 方向键 / 退格删除**故意不在里面** ——
 *  它们在画布上已经各有各的意思(确认、取消、移动焦点、平移、删除选中)。 */
export const NAMED_KEYS = [
  "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
  "Home", "End", "PageUp", "PageDown",
] as const;

export function normalizeKey(raw: string): string | null {
  if ((NAMED_KEYS as readonly string[]).includes(raw)) return raw;
  // 单个可打印字符。控制字符长度也是 1,放进来就存下了一个永远按不出来的绑定。
  if (raw.length === 1 && !/[\p{C}\p{Z}]/u.test(raw)) return raw.toUpperCase();
  return null;
}

/**
 * 一次按键 → 规范串。返回 null 表示这次按的只是修饰键本身,还没构成一个组合。
 *
 * **先看 `code` 再看 `key`**:macOS 上按住 ⌥ 会把 `key` 换成另一个字符(⌥K 是 "˚"),
 * 而 `code` 里的 `KeyK` / `Digit1` 说的是那颗物理键。只认 `key` 的话,绑的是「⌥˚」——
 * 用户在设置里看到的是一个他打不出来的符号。
 */
export function comboFromEvent(
  event: Pick<KeyboardEvent, "key" | "code" | "metaKey" | "ctrlKey" | "altKey" | "shiftKey">,
): Combo | null {
  if (["Shift", "Control", "Alt", "Meta", "CapsLock", "Dead"].includes(event.key)) return null;
  const physical = /^Key([A-Z])$/.exec(event.code ?? "")?.[1] ?? /^Digit([0-9])$/.exec(event.code ?? "")?.[1];
  const key = physical ?? normalizeKey(event.key);
  if (!key) return null;
  const parts: string[] = [];
  if (event.metaKey || event.ctrlKey) parts.push("Mod");
  if (event.altKey) parts.push("Alt");
  if (event.shiftKey) parts.push("Shift");
  return [...parts, key].join("+");
}

/** 把用户输入 / 存下来的串归一。不合法返回 null。 */
export function normalizeCombo(raw: string): Combo | null {
  const parts = raw.split("+").map((part) => part.trim()).filter(Boolean);
  if (!parts.length) return null;
  const key = normalizeKey(parts[parts.length - 1]!);
  if (!key) return null;
  const seen = new Set<string>();
  const alias: Record<string, string> = {
    mod: "Mod", cmd: "Mod", meta: "Mod", ctrl: "Mod", control: "Mod",
    alt: "Alt", option: "Alt", shift: "Shift",
  };
  for (const part of parts.slice(0, -1)) {
    const canonical = alias[part.toLowerCase()];
    if (!canonical || seen.has(canonical)) return null;
    seen.add(canonical);
  }
  return [...MODIFIER_ORDER.filter((one) => seen.has(one)), key].join("+");
}

const APPLE = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

/** 给人看的样子:macOS 是 ⌘⌥⇧K,别处是 Ctrl+Alt+Shift+K。 */
export function formatCombo(combo: Combo): string {
  const parts = combo.split("+");
  const key = parts[parts.length - 1]!;
  const mods = new Set(parts.slice(0, -1));
  if (APPLE) {
    return `${mods.has("Mod") ? "⌘" : ""}${mods.has("Alt") ? "⌥" : ""}${mods.has("Shift") ? "⇧" : ""}${key}`;
  }
  return [...MODIFIER_ORDER.filter((one) => mods.has(one)).map((one) => (one === "Mod" ? "Ctrl" : one)), key].join("+");
}

/** 焦点在能打字的地方时,所有单键快捷键都要让路 —— 否则用户打个 "1" 就被传送走了。 */
export function isTypingTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  if (!element || typeof element.tagName !== "string") return false;
  return element.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(element.tagName);
}

/**
 * 应用自己占着的键。`owner` 是**做什么用的**,不是"在哪个页面" —— 拒绝的时候要让用户
 * 一眼知道这个键已经是干什么的,页面名字帮不上忙(他此刻就在那个页面上)。
 */
export const RESERVED_COMBOS: ReadonlyArray<{ combo: Combo; owner: MessageKey }> = [
  { combo: "Mod+Z", owner: "undo" },
  { combo: "Mod+Shift+Z", owner: "redo" },
  { combo: "Mod+Y", owner: "redo" },
  { combo: "Mod+C", owner: "copy" },
  { combo: "Mod+X", owner: "shortcutOwnerCut" },
  { combo: "Mod+V", owner: "shortcutOwnerPaste" },
  { combo: "Mod+A", owner: "shortcutOwnerSelectAll" },
  { combo: "Mod+D", owner: "shortcutOwnerDuplicate" },
  { combo: "Mod+G", owner: "shortcutOwnerGroup" },
  { combo: "Mod+N", owner: "shortcutOwnerAdd" },
  { combo: "Mod+S", owner: "save" },
  { combo: "Mod+K", owner: "shortcutOwnerCommand" },
  { combo: "Mod+F", owner: "shortcutOwnerSearch" },
  { combo: "Mod+[", owner: "shortcutOwnerSendBack" },
  { combo: "Mod+]", owner: "shortcutOwnerBringFront" },
  // 剪辑页的单键工具:S 切分、A 选择、B 刀。
  { combo: "S", owner: "shortcutOwnerSplit" },
  { combo: "A", owner: "shortcutOwnerSelectTool" },
  { combo: "B", owner: "shortcutOwnerBladeTool" },
  // 3D 场景页照 Blender 的手势:G/R/S 移动旋转缩放、I 记关键帧、⌥I 移除、⇧D 复制、
  // X 删除、F 聚焦。S 和上面那条是同一个键(缩放 / 切分),名单里只留一条。
  { combo: "F", owner: "shortcutOwnerFocus" },
  { combo: "G", owner: "shortcutOwnerMove" },
  { combo: "R", owner: "shortcutOwnerRotate" },
  { combo: "I", owner: "shortcutOwnerKeyframe" },
  { combo: "Alt+I", owner: "shortcutOwnerKeyframeClear" },
  { combo: "Shift+D", owner: "shortcutOwnerDuplicate" },
  { combo: "X", owner: "shortcutOwnerDelete" },
  // 浏览器自己的,劫持不掉(或者劫持了会更糟):新窗口、关标签、刷新、地址栏、打印、缩放。
  { combo: "Mod+W", owner: "shortcutOwnerBrowser" },
  { combo: "Mod+T", owner: "shortcutOwnerBrowser" },
  { combo: "Mod+R", owner: "shortcutOwnerBrowser" },
  { combo: "Mod+Q", owner: "shortcutOwnerBrowser" },
  { combo: "Mod+P", owner: "shortcutOwnerBrowser" },
  { combo: "Mod+L", owner: "shortcutOwnerBrowser" },
  { combo: "Mod+0", owner: "shortcutOwnerBrowser" },
];

/** 这个组合已经归应用所有吗?是的话给出它归谁 —— 不是的话返回 null。 */
export function reservedOwner(combo: Combo): MessageKey | null {
  return RESERVED_COMBOS.find((one) => one.combo === combo)?.owner ?? null;
}
