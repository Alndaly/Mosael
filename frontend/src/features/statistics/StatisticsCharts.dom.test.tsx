/** @vitest-environment jsdom */
/**
 * 费用那一格:**一张图只画一种钱。**
 *
 * 人民币和美元不能叠在同一根柱子上,也不能共用一条纵轴。多币种时标题行上有一个币种切换,
 * 默认是主要币种(后端把它排在 costs 第一笔);图、提示框和下面的供应商分摊跟着同一个选择走。
 *
 * Recharts 在 jsdom 里没有尺寸、什么都不画,所以把图表外壳换成直接把数据写出来的桩 ——
 * 这里要看的是"喂给图的是哪一种钱",不是 SVG。
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "en-US" }) }));
vi.mock("recharts", () => ({
  BarChart: ({ data, children }: { data: Array<{ cost: number }>; children: React.ReactNode }) => (
    <div>
      <output data-testid="bars">{data.map((day) => day.cost).join(",")}</output>
      {children}
    </div>
  ),
  Bar: () => null,
  CartesianGrid: () => null,
  XAxis: () => null,
  Cell: () => null,
  Pie: () => null,
  PieChart: () => null,
}));
vi.mock("@/components/app/chart", () => ({
  ChartContainer: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  ChartTooltip: ({ content }: { content: React.ReactNode }) => <>{content}</>,
  ChartTooltipContent: ({ valueFormatter }: { valueFormatter: (value: number) => React.ReactNode }) => (
    <output data-testid="tooltip">{valueFormatter(4_500_000)}</output>
  ),
  ChartLegend: ({ content }: { content: React.ReactNode }) => <>{content}</>,
  ChartLegendContent: ({ extra }: { extra: React.ReactNode }) => <>{extra}</>,
}));

const { UsageCostChart, UsageCostPanel } = await import("./StatisticsCharts");

const CNY = (micros: number) => ({ currency: "CNY", micros });
const USD = (micros: number) => ({ currency: "USD", micros });

function panel(costs: Array<{ currency: string; micros: number }>) {
  return render(
    <UsageCostPanel
      title="homeChartUsage"
      costs={costs}
      unknown={0}
      unpriced={[]}
      daily={[
        { date: "2026-09-23", costs: [CNY(8_000_000)], events: 2, unknown: 0 },
        { date: "2026-09-24", costs: [CNY(4_000_000), USD(4_500_000)], events: 2, unknown: 0 },
      ]}
      byProvider={{ alibaba: [CNY(12_000_000)], openai: [USD(4_500_000)] }}
    />,
  );
}

it("两种钱时默认画主要币种,切换后图、提示框、供应商分摊一起换", () => {
  panel([CNY(12_000_000), USD(4_500_000)]);

  const cny = screen.getByRole("radio", { name: "CNY" });
  const usd = screen.getByRole("radio", { name: "USD" });
  expect(cny).toHaveAttribute("aria-checked", "true");
  expect(screen.getByTestId("bars")).toHaveTextContent("8000000,4000000");
  expect(screen.getByTestId("tooltip")).toHaveTextContent("CN¥4.50");
  expect(screen.getByText("alibaba")).toBeInTheDocument();
  expect(screen.queryByText("openai")).toBeNull();
  // 图下面说清为什么一次只看一种。
  expect(screen.getByText("homeChartUsageCurrencyHint")).toBeInTheDocument();

  fireEvent.click(usd);
  expect(usd).toHaveAttribute("aria-checked", "true");
  // 美元那天之外是 0 —— 不是把人民币那笔画进来。
  expect(screen.getByTestId("bars")).toHaveTextContent("0,4500000");
  expect(screen.getByTestId("tooltip")).toHaveTextContent("$4.50");
  expect(screen.getByText("openai")).toBeInTheDocument();
  expect(screen.queryByText("alibaba")).toBeNull();
});

it("只有一种钱时没有切换,也不多一句解释", () => {
  panel([CNY(12_000_000)]);
  expect(screen.queryByRole("radiogroup")).toBeNull();
  expect(screen.queryByText("homeChartUsageCurrencyHint")).toBeNull();
  expect(screen.getByTestId("bars")).toHaveTextContent("8000000,4000000");
});

/**
 * 一笔都没计上价时,空态给下一步 —— 但**价格规则只有部署管理员写得了**(在管理页)。
 * 给普通成员一个「去设置价格规则」,点进去是一个他打不开的页面;所以他那里只说一句归谁维护。
 */
function unpricedChart(onConfigurePricing?: () => void) {
  return render(
    <UsageCostChart
      currency=""
      unknown={3}
      unpriced={[{ provider: "openai", model: "gpt-x", events: 3, reason: "no_rule" }] as never}
      daily={[{ date: "2026-09-24", costs: [], events: 3, unknown: 3 }]}
      onConfigurePricing={onConfigurePricing}
    />,
  );
}

it("未定价:管理员拿到去配价格的按钮", () => {
  const configure = vi.fn();
  unpricedChart(configure);
  fireEvent.click(screen.getByRole("button", { name: "homeChartUsageConfigurePricing" }));
  expect(configure).toHaveBeenCalledOnce();
});

it("未定价:普通成员没有按钮,只说价格归管理员维护", () => {
  unpricedChart();
  expect(screen.queryByRole("button", { name: "homeChartUsageConfigurePricing" })).toBeNull();
  expect(screen.getByText("homeChartUsagePricingByAdmin")).toBeInTheDocument();
});
