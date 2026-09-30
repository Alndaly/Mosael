import { describe, expect, it } from "vitest";

import { listFromRows, rowsFromList } from "@/features/nodeForms/ListField";

describe("插件的数组入参存成数组,不是「名字 → 值」的对象", () => {
  it("一行一项,存下去是数组", () => {
    // 此前这类字段拿到的是映射编辑器,存下去是 {"a": …},交给插件的就不是数组。
    expect(listFromRows(["第一段", "{{llm-1.text}}"])).toEqual(["第一段", "{{llm-1.text}}"]);
  });

  it("空行丢掉;数字、布尔还原类型;引用一律当字符串", () => {
    expect(listFromRows(["", "3", "true", "  ", "{{n.count}}"])).toEqual([3, true, "{{n.count}}"]);
  });

  it("存着的数组还原成行;一整串引用(还没展开的 {{…}})给一行", () => {
    expect(rowsFromList(["a", 2])).toEqual(["a", "2"]);
    expect(rowsFromList("{{split.items}}")).toEqual(["{{split.items}}"]);
    expect(rowsFromList(undefined)).toEqual([]);
  });
});
