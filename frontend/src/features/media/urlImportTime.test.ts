/**
 * 时间段输入。
 *
 * 这里的每条断言都对着一种"看起来能用、实际出空文件"的写法:把没填当成 0、把结束≤开始当成
 * 合法区间、把 `1:30` 当成 1.5 秒。截取本身是为了不下满两小时,而这些错法会让人下回一个空文件,
 * 然后以为功能坏了。
 */
import { describe, expect, it } from "vitest";

import { parseTimecode, toSection } from "./urlImportTime";

describe("时间码解析", () => {
  it("三种写法都认:纯秒、分:秒、时:分:秒", () => {
    expect(parseTimecode("90")).toBe(90);
    expect(parseTimecode("1:30")).toBe(90);
    expect(parseTimecode("1:02:03")).toBe(3723);
  });

  it("空 = 不限,而不是 0 —— 只填结束的人要的是「从头到这里」", () => {
    expect(parseTimecode("")).toBeNull();
    expect(parseTimecode("   ")).toBeNull();
  });

  it("乱填不当成 0 —— 当成 0 会安静地下回一个从头开始的整片", () => {
    expect(parseTimecode("abc")).toBeNull();
    expect(parseTimecode("1:2:3:4")).toBeNull();
    expect(parseTimecode("1::2")).toBeNull();
  });
});

describe("区间", () => {
  it("两头都空 = 不截取", () => {
    expect(toSection("", "")).toBeNull();
  });

  it("只填开始 = 从这里到结尾", () => {
    expect(toSection("0:30", "")).toEqual({ start: 30, end: Number.MAX_SAFE_INTEGER });
  });

  it("只填结束 = 从头到这里", () => {
    expect(toSection("", "0:30")).toEqual({ start: 0, end: 30 });
  });

  it("结束不晚于开始 = 无效,而不是一个空区间", () => {
    expect(toSection("1:00", "0:30")).toBeNull();
    expect(toSection("1:00", "1:00")).toBeNull();
  });
});
