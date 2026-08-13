"use client";

import * as React from "react";
import * as RechartsPrimitive from "recharts";

import { cn } from "@/lib/utils";

/**
 * shadcn/ui chart 基件(Recharts 包装),按本项目裁剪:
 * - 颜色经 ChartConfig 注入为 --color-<key>,值引用 tokens.css 里
 *   dataviz 校验过的 --chart-*(不引入 shadcn 默认的 --chart-1..5 调色)
 * - 无阴影、发丝边框、文本用文本色——与全局设计纪律一致
 */

export type ChartConfig = {
  [k in string]: {
    label?: React.ReactNode;
    icon?: React.ComponentType;
    color?: string;
  };
};

type ChartContextProps = { config: ChartConfig };

const ChartContext = React.createContext<ChartContextProps | null>(null);

function useChart() {
  const context = React.useContext(ChartContext);
  if (!context) throw new Error("useChart must be used within a <ChartContainer />");
  return context;
}

function ChartContainer({
  id,
  className,
  children,
  config,
  ...props
}: React.ComponentProps<"div"> & {
  config: ChartConfig;
  children: React.ComponentProps<typeof RechartsPrimitive.ResponsiveContainer>["children"];
}) {
  const uniqueId = React.useId();
  const chartId = `chart-${id || uniqueId.replace(/:/g, "")}`;

  return (
    <ChartContext.Provider value={{ config }}>
      <div data-chart={chartId} className={cn(
          "w-full [&_.recharts-cartesian-axis-tick_text]:fill-muted-foreground [&_.recharts-cartesian-axis-tick_text]:text-ui-2xs [&_.recharts-cartesian-axis-tick_text]:tabular-nums [&_.recharts-cartesian-grid_line]:stroke-border",
          className,
        )} {...props}>
        <ChartStyle id={chartId} config={config} />
        <RechartsPrimitive.ResponsiveContainer>{children}</RechartsPrimitive.ResponsiveContainer>
      </div>
    </ChartContext.Provider>
  );
}

// 注入的内容只来自源码里的 ChartConfig 字面量,但仍按白名单过滤(纵深防御):
// key 限 [a-z0-9-],color 限 hex / var(--*) / rgb()/hsl(),其余一律丢弃。
const SAFE_KEY = /^[a-zA-Z0-9-]+$/;
const SAFE_COLOR = /^(#[0-9a-fA-F]{3,8}|var\(--[a-zA-Z0-9-]+\)|(rgb|rgba|hsl|hsla|oklch)\([^)]*\))$/;

const ChartStyle = ({ id, config }: { id: string; config: ChartConfig }) => {
  const entries = Object.entries(config).filter(
    ([key, item]) => item.color && SAFE_KEY.test(key) && SAFE_COLOR.test(item.color),
  );
  if (!entries.length) return null;
  return (
    <style
      dangerouslySetInnerHTML={{
        __html: `[data-chart=${id}] {\n${entries
          .map(([key, item]) => `  --color-${key}: ${item.color};`)
          .join("\n")}\n}`,
      }}
    />
  );
};

const ChartTooltip = RechartsPrimitive.Tooltip;

function ChartTooltipContent({
  active,
  payload,
  label,
  hideLabel = false,
  labelFormatter,
  valueFormatter,
}: {
  active?: boolean;
  payload?: Array<{ name?: string; dataKey?: string | number; value?: number | string; color?: string }>;
  label?: unknown;
  hideLabel?: boolean;
  labelFormatter?: (label: unknown) => React.ReactNode;
  valueFormatter?: (value: number | string) => React.ReactNode;
}) {
  const { config } = useChart();
  if (!active || !payload?.length) return null;
  return (
    <div className="grid min-w-[130px] gap-1 rounded-md border border-border-strong bg-panel px-2.5 py-1.5 text-ui-xs">
      {!hideLabel && (
        <div className="font-[650]">{labelFormatter ? labelFormatter(label) : String(label ?? "")}</div>
      )}
      {payload.map((item) => {
        const key = String(item.dataKey ?? item.name ?? "");
        const entry = config[key];
        return (
          <div className="flex items-center gap-1.5" key={key}>
            <span className="inline-block h-2 w-2 flex-none rounded-full" style={{ background: entry?.color ?? item.color }} />
            <span className="text-muted-foreground">{entry?.label ?? key}</span>
            <span className="ml-auto tabular-nums">
              {valueFormatter ? valueFormatter(item.value ?? 0) : item.value}
            </span>
          </div>
        );
      })}
    </div>
  );
}

const ChartLegend = RechartsPrimitive.Legend;

function ChartLegendContent({
  payload,
  extra,
}: {
  payload?: Array<{ value?: string; dataKey?: string | number; color?: string }>;
  extra?: React.ReactNode;
}) {
  const { config } = useChart();
  if (!payload?.length) return null;
  return (
    <div className="flex flex-wrap gap-3 pt-1 text-ui-xs text-muted-foreground">
      {payload.map((item) => {
        const key = String(item.dataKey ?? item.value ?? "");
        const entry = config[key];
        return (
          <span className="inline-flex items-center gap-[5px]" key={key}>
            <i className="inline-block h-2 w-2 flex-none rounded-full" style={{ background: entry?.color ?? item.color }} /> {entry?.label ?? key}
          </span>
        );
      })}
      {extra}
    </div>
  );
}

export { ChartContainer, ChartTooltip, ChartTooltipContent, ChartLegend, ChartLegendContent, ChartStyle };
