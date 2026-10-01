import { describe, expect, it } from "vitest";

import { listFromRows, rowsFromList } from "@/features/nodeForms/ListField";

describe("插件的数组入参存成数组,不是「名字 → 值」的对象", () => {
  it("一行一项,存下去是数组", () => {
    // 此前这类字段拿到的是映射编辑器,存下去是 {"a": …},交给插件的就不是数组。
    expect(listFromRows(["第一段", "{{llm-1.text}}"])).toEqual(["第一段", "{{llm-1.text}}"]);
  });

  it("空行丢掉;其余一律存文字 —— 是不是数由后端按 items.type 转", () => {
    expect(listFromRows(["", "3", "true", "  ", "{{n.count}}"])).toEqual(["3", "true", "{{n.count}}"]);
  });

  it("像数的字符串不改形:前导零、十九位的长 id 原样存下", () => {
    // 此前「像数的」一律转成数:声明成字符串的 "007" 存成 7,长 id 绕一道浮点数丢了末几位。
    expect(listFromRows(["007", "7342567890123457123", "1e3"])).toEqual(["007", "7342567890123457123", "1e3"]);
  });

  it("存着的数组还原成行;一整串引用(还没展开的 {{…}})给一行", () => {
    expect(rowsFromList(["a", 2])).toEqual(["a", "2"]);
    expect(rowsFromList("{{split.items}}")).toEqual(["{{split.items}}"]);
    expect(rowsFromList(undefined)).toEqual([]);
  });
});
