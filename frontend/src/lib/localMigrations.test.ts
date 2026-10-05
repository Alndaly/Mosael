/**
 * 本机设置的一次性迁移(见 lib/localMigrations):旧形状进、新形状出,幂等,迁完旧键删掉 —— 之后没有代码读它。
 */

import { beforeEach, expect, it, vi } from "vitest";

import { runLocalMigrations } from "@/lib/localMigrations";

/** 一个够用的 Storage(Map 撑着)。 */
function storage(entries: Record<string, string> = {}): Storage {
  const map = new Map(Object.entries(entries));
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (key) => map.get(key) ?? null,
    key: (index) => [...map.keys()][index] ?? null,
    removeItem: (key) => void map.delete(key),
    setItem: (key, value) => void map.set(key, String(value)),
  };
}

beforeEach(() => vi.restoreAllMocks());

it("「模糊预览图」开着 → 预览图重度模糊;关着 → 清晰;NSFW 那一组用缺省(模糊);旧键删掉", () => {
  const on = storage({ "mosael:tab:model-library.blur": "on" });
  runLocalMigrations(on);
  expect(JSON.parse(on.getItem("mosael:model-previews")!)).toEqual({ level: "heavy", nsfw: "blur" });
  expect(on.getItem("mosael:tab:model-library.blur")).toBeNull();

  const off = storage({ "mosael:tab:model-library.blur": "off" });
  runLocalMigrations(off);
  expect(JSON.parse(off.getItem("mosael:model-previews")!)).toEqual({ level: "clear", nsfw: "blur" });
  expect(off.getItem("mosael:tab:model-library.blur")).toBeNull();
});

it("幂等:再跑一遍什么都不改;已经有新设置的不覆盖(旧键照样删);认不出的旧值只删不迁", () => {
  const once = storage({ "mosael:tab:model-library.blur": "on" });
  runLocalMigrations(once);
  const after = once.getItem("mosael:model-previews");
  runLocalMigrations(once);
  expect(once.getItem("mosael:model-previews")).toBe(after);

  const both = storage({ "mosael:tab:model-library.blur": "on", "mosael:model-previews": JSON.stringify({ level: "clear", nsfw: "hidden" }) });
  runLocalMigrations(both);
  expect(JSON.parse(both.getItem("mosael:model-previews")!)).toEqual({ level: "clear", nsfw: "hidden" });
  expect(both.getItem("mosael:tab:model-library.blur")).toBeNull();

  const junk = storage({ "mosael:tab:model-library.blur": "maybe" });
  runLocalMigrations(junk);
  expect(junk.getItem("mosael:model-previews")).toBeNull();
  expect(junk.getItem("mosael:tab:model-library.blur")).toBeNull();
});

it("一步失败(存储坏了)不挡应用启动", () => {
  const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  const broken = { ...storage(), getItem: () => { throw new Error("denied"); } } as unknown as Storage;
  expect(() => runLocalMigrations(broken)).not.toThrow();
  expect(warn).toHaveBeenCalled();
});
