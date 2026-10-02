import { describe, expect, it } from "vitest";

import { cueTrim, parseCueTime } from "@/features/editor/cueTiming";

describe("字幕起止时间", () => {
  it("认秒、分:秒、时:分:秒,逗号当小数点", () => {
    expect(parseCueTime("12.5")).toBe(12.5);
    expect(parseCueTime("01:02.5")).toBe(62.5);
    expect(parseCueTime("1:02:03,25")).toBeCloseTo(3723.25);
    expect(parseCueTime("abc")).toBeNull();
    expect(parseCueTime("")).toBeNull();
    expect(parseCueTime("1:2:3:4")).toBeNull();
  });

  it("起止换成一次 trim;终点不晚于起点就不改", () => {
    expect(cueTrim(1, 3.5)).toEqual({ timeline_start: 1, src_in: 0, src_out: 2.5 });
    expect(cueTrim(3, 3)).toBeNull();
    expect(cueTrim(-1, 2)).toBeNull();
  });
});
