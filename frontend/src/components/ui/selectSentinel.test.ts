/**
 * 「不选」在下拉里也得是一个**有值的**选项。
 *
 * radix 的 `Select` 把空字符串当成「还没选」:`<SelectItem value="">` 选中之后 `SelectValue`
 * 认为无值可显示,触发器一片空白 —— 用户明明点了「不用」,看到的却是没选(截图为证)。
 *
 * 这个坑一次写出了两处(配音的「权重」、从链接导入的「登录身份」),所以除了收成一份哨兵,
 * 还扫一遍源码:再有人写 `value=""` 就在这里红。
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { NONE, optionalValue } from "./selectSentinel";

const SRC = join(import.meta.dirname, "..", "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return entry.name.endsWith(".tsx") ? [full] : [];
  });
}

describe("下拉里的「不选」", () => {
  it("哨兵不是空字符串 —— 空字符串会让触发器显示空白", () => {
    expect(NONE).not.toBe("");
    expect(NONE.trim()).not.toBe("");
  });

  it("送出去时翻译回 null,其余原样", () => {
    expect(optionalValue(NONE)).toBeNull();
    expect(optionalValue("")).toBeNull(); // 历史值也当「没选」
    expect(optionalValue("profile-1")).toBe("profile-1");
  });

  it("源码里不再有 `SelectItem value=\"\"`", () => {
    const offenders = sourceFiles(SRC).filter((file) =>
      /<SelectItem\s+value=""/.test(readFileSync(file, "utf8")),
    );
    expect(offenders.map((file) => file.replace(SRC, ""))).toEqual([]);
  });
});
