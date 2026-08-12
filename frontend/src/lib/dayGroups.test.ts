/**
 * 按「哪一天」分组。
 *
 * 两个容易错的地方,各钉一条:
 *
 * 1. **后端给的是无时区标记的 UTC 串**(`2026-07-30T10:18:01.163532`,见 lib/time 的同款说明)。
 *    直接 `new Date(那串)` 会被当成本地时间 —— 东八区的用户看到的日期就会整体偏 8 小时,
 *    晚上八点之后发的记录全部掉到"昨天"那一栏。
 * 2. **分组要按用户的日历天**,不是 UTC 的天。UTC 分组会在本地时间的白天正中间切一刀。
 *
 * 这两条合起来只有一个正确解:按 UTC 解析,按**本地**日历天归类。
 */
import { describe, expect, it } from "vitest";

import { dayGroupOf, groupByLocalDay } from "@/lib/dayGroups";

/** 造一条后端那样的时间串:给定「本地」年月日时分,转成无 Z 的 UTC ISO。
 *  `new Date(年,月,日,…)` 给出的就是那个本地墙上时间对应的时刻,所以直接 toISOString 即可 ——
 *  再手动减一次时区偏移会把时间挪两遍(第一版就是这么错的,被这几条测试当场逮住)。 */
function backendIsoForLocal(year: number, month: number, day: number, hour: number, minute = 0): string {
  return new Date(year, month - 1, day, hour, minute).toISOString().replace("Z", "");
}

const at = (iso: string) => ({ created_at: iso });

describe("按本地日分组", () => {
  it("同一本地日的进同一组", () => {
    const items = [at(backendIsoForLocal(2026, 7, 30, 23, 30)), at(backendIsoForLocal(2026, 7, 30, 1, 0))];

    const groups = groupByLocalDay(items, (item) => item.created_at);

    expect(groups).toHaveLength(1);
    expect(groups[0].items).toHaveLength(2);
  });

  it("跨本地午夜的两条分成两组 —— 哪怕只差一分钟", () => {
    const items = [at(backendIsoForLocal(2026, 7, 31, 0, 1)), at(backendIsoForLocal(2026, 7, 30, 23, 59))];

    const groups = groupByLocalDay(items, (item) => item.created_at);

    expect(groups.map((group) => group.key)).toEqual(["2026-07-31", "2026-07-30"]);
  });

  it("保持传入顺序(新的在前),组内也保持", () => {
    const items = [
      at(backendIsoForLocal(2026, 7, 31, 9)),
      at(backendIsoForLocal(2026, 7, 30, 18)),
      at(backendIsoForLocal(2026, 7, 30, 8)),
    ];

    const groups = groupByLocalDay(items, (item) => item.created_at);

    expect(groups.map((group) => group.key)).toEqual(["2026-07-31", "2026-07-30"]);
    expect(groups[1].items.map((item) => item.created_at)).toEqual([items[1].created_at, items[2].created_at]);
  });

  it("空列表给空数组,不是一个空分组", () => {
    expect(groupByLocalDay([], (item: { created_at: string }) => item.created_at)).toEqual([]);
  });

  it("解析不出来的时间串单独归到一组,而不是把整页搞崩", () => {
    const groups = groupByLocalDay([at("not-a-date")], (item) => item.created_at);

    expect(groups).toHaveLength(1);
    expect(groups[0].key).toBe("");
  });
});

describe("这一天怎么称呼", () => {
  const today = new Date(2026, 6, 31, 15, 0);

  it("今天 / 昨天 给出种类,让调用方去取对应文案", () => {
    expect(dayGroupOf("2026-07-31", today).kind).toBe("today");
    expect(dayGroupOf("2026-07-30", today).kind).toBe("yesterday");
    expect(dayGroupOf("2026-07-29", today).kind).toBe("other");
  });

  it("更早的日子给可读日期(而不是 2026-07-29 这种机器串)", () => {
    const { text } = dayGroupOf("2026-07-29", today, "zh-CN");

    expect(text).toContain("7");
    expect(text).toContain("29");
    expect(text).not.toBe("2026-07-29");
  });

  it("跨年时不会把去年的同一天认成今天", () => {
    expect(dayGroupOf("2025-07-31", today).kind).toBe("other");
  });
});
