import { describe, expect, it } from "vitest";

import { markerShortcutConflict, nextMarkerName, newMarkerId, type CanvasMarker } from "@/features/markers/markers";
import { comboFromEvent, formatCombo, normalizeCombo, RESERVED_COMBOS } from "@/lib/shortcuts";

const marker = (id: string, name: string, shortcut?: string): CanvasMarker => ({ id, name, x: 0, y: 0, shortcut });

const press = (init: Partial<KeyboardEvent> & { key: string }) =>
  comboFromEvent({ code: "", metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, ...init } as KeyboardEvent);

describe("快捷键归一", () => {
  it("⌘ 和 Ctrl 是同一个 Mod —— 否则同一张画板在两个系统上有两套绑定", () => {
    expect(press({ key: "1", code: "Digit1", metaKey: true })).toBe("Mod+1");
    expect(press({ key: "1", code: "Digit1", ctrlKey: true })).toBe("Mod+1");
    expect(normalizeCombo("cmd+1")).toBe(normalizeCombo("ctrl+1"));
  });

  it("修饰键顺序和大小写不影响它是不是同一个绑定", () => {
    expect(normalizeCombo("shift+mod+k")).toBe("Mod+Shift+K");
    expect(normalizeCombo("Mod+Shift+K")).toBe("Mod+Shift+K");
  });

  it("按 ⌥ 时认物理键位,不认 macOS 换过的那个字符", () => {
    // ⌥K 在 macOS 上的 event.key 是 "˚":存下来的话,用户在设置里看到一个他打不出来的符号。
    expect(press({ key: "˚", code: "KeyK", altKey: true })).toBe("Alt+K");
  });

  it("只按下修饰键还不算一个组合", () => {
    expect(press({ key: "Shift", shiftKey: true })).toBeNull();
    expect(press({ key: "Meta", metaKey: true })).toBeNull();
  });

  it("Enter / Escape / 方向键这些绑不了 —— 它们在画布上已经各有各的意思", () => {
    for (const key of ["Enter", "Escape", "Tab", "ArrowUp", "Backspace", "Delete", " "]) {
      expect(normalizeCombo(key)).toBeNull();
    }
  });

  it("显示成人看得懂的样子", () => {
    // 平台相关,只钉住"键名一定在,而且修饰键不会被漏掉"。
    const shown = formatCombo("Mod+Shift+K");
    expect(shown).toContain("K");
    expect(shown.length).toBeGreaterThan(1);
  });
});

describe("标记的快捷键冲突", () => {
  const existing = [marker("a", "开头", "Alt+1"), marker("b", "结尾")];

  it("和应用已有的快捷键撞了就不给配,并且说得出它归谁", () => {
    const conflict = markerShortcutConflict("Mod+Z", existing, "b");
    expect(conflict).toEqual({ reason: "reserved", owner: "undo" });
  });

  it("和另一个标记撞了就不给配,并且说得出是哪一个", () => {
    expect(markerShortcutConflict("alt+1", existing, "b")).toEqual({ reason: "marker", markerName: "开头" });
  });

  it("改绑到自己已经占着的那个键上不算冲突", () => {
    expect(markerShortcutConflict("Alt+1", existing, "a")).toBeNull();
  });

  it("能绑的组合放行", () => {
    expect(markerShortcutConflict("Alt+2", existing, "b")).toBeNull();
    expect(markerShortcutConflict("Mod+Alt+9", existing, "b")).toBeNull();
  });

  it("绑不出来的键当场拒绝,而不是存成一个永远按不出来的组合", () => {
    expect(markerShortcutConflict("Enter", existing, "b")).toEqual({ reason: "invalid" });
    expect(markerShortcutConflict("", existing, "b")).toEqual({ reason: "invalid" });
  });
});

describe("保留键名单", () => {
  it("每一条都是规范形态 —— 不然它永远匹配不上用户按出来的那个串", () => {
    for (const { combo } of RESERVED_COMBOS) expect(normalizeCombo(combo)).toBe(combo);
  });

  it("没有重复(重复意味着其中一条的 owner 永远显示不出来)", () => {
    const combos = RESERVED_COMBOS.map((one) => one.combo);
    expect(new Set(combos).size).toBe(combos.length);
  });
});

describe("默认命名", () => {
  it("按已占用的名字找空位:删掉中间一个再新建,正好补回那个空位", () => {
    const markers = [marker("m1", "标记 1"), marker("m3", "标记 3")];
    expect(nextMarkerName("标记", markers)).toBe("标记 2");
    expect(newMarkerId([marker("marker-1", "x"), marker("marker-3", "y")])).toBe("marker-2");
  });
});
