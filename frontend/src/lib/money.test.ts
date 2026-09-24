/**
 * 金额格式化 —— 全项目只有这一份(lib/money)。
 *
 * **不同币种的钱不相加**:一组各币种的钱写成 `¥12.30 + US$4.50`,而不是加成一个数、再随便贴上
 * 其中一种单位。
 */
import { describe, expect, it } from "vitest";
import { formatCosts, formatMoney, microsIn, sumByCurrency } from "./money";

describe("formatMoney", () => {
  it("按界面语言的习惯写币种符号", () => {
    expect(formatMoney(12_300_000, "CNY", "zh-CN")).toBe("¥12.30");
    expect(formatMoney(4_500_000, "USD", "zh-CN")).toBe("US$4.50");
    expect(formatMoney(4_500_000, "USD", "en-US")).toBe("$4.50");
    expect(formatMoney(12_300_000, "CNY", "en-US")).toBe("CN¥12.30");
  });

  it("小额留够精度:一次几厘钱的调用不能压成 0.00", () => {
    expect(formatMoney(1_500, "USD", "en-US")).toBe("$0.0015");
    expect(formatMoney(123_400, "USD", "en-US")).toBe("$0.1234");
    expect(formatMoney(0, "USD", "en-US")).toBe("$0.00");
  });

  it("大额取整并分组", () => {
    expect(formatMoney(12_345_600_000, "CNY", "zh-CN")).toBe("¥12,346");
  });

  it("Intl 不认的币种代码照样显示,单位跟在后面", () => {
    expect(formatMoney(2_000_000, "X", "en-US")).toBe("2.00 X");
  });
});

describe("formatCosts", () => {
  it("一种钱就是一笔", () => {
    expect(formatCosts([{ currency: "USD", micros: 1_500 }], "en-US")).toBe("$0.0015");
  });

  it("两种钱各写一笔,用 + 连起来,不加成一个数", () => {
    const text = formatCosts(
      [
        { currency: "CNY", micros: 12_300_000 },
        { currency: "USD", micros: 4_500_000 },
      ],
      "zh-CN",
    );
    expect(text).toBe("¥12.30 + US$4.50");
    expect(text).not.toContain("16.8");
  });

  it("没有钱是空串,由调用方决定怎么说", () => {
    expect(formatCosts([], "en-US")).toBe("");
    expect(formatCosts(undefined, "en-US")).toBe("");
  });
});

describe("sumByCurrency", () => {
  it("只在同一币种内相加,次数多的币种在前", () => {
    expect(
      sumByCurrency([
        { currency: "USD", micros: 1 },
        { currency: "CNY", micros: 10 },
        { currency: "CNY", micros: 20 },
      ]),
    ).toEqual([
      { currency: "CNY", micros: 30 },
      { currency: "USD", micros: 1 },
    ]);
  });

  it("次数相同按币种代码排,顺序不随输入漂", () => {
    const one = sumByCurrency([{ currency: "USD", micros: 1 }, { currency: "CNY", micros: 2 }]);
    const two = sumByCurrency([{ currency: "CNY", micros: 2 }, { currency: "USD", micros: 1 }]);
    expect(one).toEqual(two);
    expect(one.map((cost) => cost.currency)).toEqual(["CNY", "USD"]);
  });
});

it("microsIn 取某一币种那一笔,没有就是 0", () => {
  const costs = [{ currency: "CNY", micros: 5 }];
  expect(microsIn(costs, "CNY")).toBe(5);
  expect(microsIn(costs, "USD")).toBe(0);
  expect(microsIn(undefined, "USD")).toBe(0);
});
