import React from "react";
import { Trash2 } from "lucide-react";

import type { components } from "@/api/generated/schema";
import { usePreferences, useI18n } from "@/app/preferences";
import { DIALOG_FIELD } from "@/components/app/modals";
import { AddRow } from "@/components/ui/add-row";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { OptionPicker } from "@/components/ui/option-picker";
import { TimePicker } from "@/components/ui/time-picker";

/**
 * 计价规则的「分时段价格」:同一条规则在一周里的某几段收另一个价(后端见 domain/price_schedule)。
 *
 * **它是这条规则价目的一部分,不是另一条规则。**币种、计价单位跟着规则走,时段只改金额;
 * 不落在任何时段里的时刻按规则的单价计。所以这一块放在单价下面,而不是在列表里多出一行。
 */

type ApiWindow = components["schemas"]["PricingTimeWindow"];

/** 表单里的一个时段。`weekdays` 在这里恒为显式的一组(全选 = 每天),提交时七天全选收成 `[]`。 */
export type WindowDraft = { start: string; end: string; weekdays: number[]; amount: string };

export const ALL_DAYS = [1, 2, 3, 4, 5, 6, 7];
const WORKDAYS = [1, 2, 3, 4, 5];
const WEEKENDS = [6, 7];
export const BEIJING = "Asia/Shanghai";

const sameDays = (a: number[], b: number[]) => a.length === b.length && a.every((day, i) => day === b[i]);

export function microsToAmount(value: number): string {
  const amount = value / 1_000_000;
  return Number.isInteger(amount) ? String(amount) : String(Number(amount.toFixed(6)));
}

export function amountToMicros(value: string): number {
  const amount = Number(value);
  if (!Number.isFinite(amount) || amount < 0) return 0;
  return Math.round(amount * 1_000_000);
}

export function draftsFromApi(windows: ApiWindow[] | undefined): WindowDraft[] {
  return (windows ?? []).map((window) => ({
    start: window.start,
    end: window.end,
    weekdays: window.weekdays?.length ? [...window.weekdays] : [...ALL_DAYS],
    amount: microsToAmount(window.unit_amount_micros),
  }));
}

export function draftsToApi(drafts: WindowDraft[]): ApiWindow[] {
  return drafts.map((draft) => {
    const days = [...draft.weekdays].sort((a, b) => a - b);
    return {
      start: draft.start,
      end: draft.end,
      weekdays: sameDays(days, ALL_DAYS) ? [] : days,
      unit_amount_micros: amountToMicros(draft.amount),
    };
  });
}

/** 这台机器所在的时区;浏览器说不出来时用 UTC。 */
export function localTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function useWeekdayNames(): (day: number) => string {
  const { locale } = usePreferences();
  return React.useMemo(() => {
    const format = new Intl.DateTimeFormat(locale === "en-US" ? "en-US" : "zh-CN", { weekday: "short", timeZone: "UTC" });
    // 2024-01-01 是周一:ISO 星期 n 就是那天往后 n-1 天。
    const names = ALL_DAYS.map((day) => format.format(new Date(Date.UTC(2024, 0, day))));
    return (day: number) => names[day - 1] ?? String(day);
  }, [locale]);
}

/** 列表行上的一小句:「工作日 09:00–12:00、14:00–18:00 2 · 北京时间」。同星期、同价的时段并成一段。 */
export function useScheduleSummary(): (windows: ApiWindow[] | undefined, timeZone: string) => string {
  const t = useI18n();
  const dayName = useWeekdayNames();
  return React.useCallback(
    (windows, timeZone) => {
      if (!windows?.length) return "";
      const groups: Array<{ days: number[]; amount: number; ranges: string[] }> = [];
      for (const window of windows) {
        const days = window.weekdays ?? [];
        const last = groups.at(-1);
        const range = `${window.start}–${window.end}`;
        if (last && sameDays(last.days, days) && last.amount === window.unit_amount_micros) last.ranges.push(range);
        else groups.push({ days, amount: window.unit_amount_micros, ranges: [range] });
      }
      const daysLabel = (days: number[]) =>
        days.length === 0
          ? ""
          : sameDays(days, WORKDAYS)
            ? t("pricingWorkdays")
            : sameDays(days, WEEKENDS)
              ? t("pricingWeekends")
              : days.map(dayName).join("/");
      const zone = timeZone === BEIJING ? t("pricingZoneBeijing") : timeZone;
      const parts = groups.map((group) =>
        [daysLabel(group.days), group.ranges.join(", "), microsToAmount(group.amount)].filter(Boolean).join(" "),
      );
      return `${parts.join("; ")} (${zone})`;
    },
    [dayName, t],
  );
}

function useTimeZoneOptions(current: string) {
  const t = useI18n();
  return React.useMemo(() => {
    let zones: string[] = [];
    try {
      zones = Intl.supportedValuesOf("timeZone");
    } catch {
      zones = [];
    }
    const all = Array.from(new Set([current, BEIJING, "UTC", ...zones].filter(Boolean)));
    return all.map((zone) => ({
      value: zone,
      label: zone === BEIJING ? `${t("pricingZoneBeijing")} · ${zone}` : zone,
      keywords: [zone.replace(/_/g, " ")],
    }));
  }, [current, t]);
}

/** 新加的一段:接在上一段后面一小时;第一段取常见的白天 09:00–18:00。单价先照抄基础价,用户再改。 */
function nextWindow(drafts: WindowDraft[], baseAmount: string): WindowDraft {
  const last = drafts.at(-1);
  if (!last) return { start: "09:00", end: "18:00", weekdays: [...ALL_DAYS], amount: baseAmount };
  const hour = (Number(last.end.slice(0, 2)) + 1) % 24;
  return { start: last.end, end: `${String(hour).padStart(2, "0")}${last.end.slice(2)}`, weekdays: [...last.weekdays], amount: baseAmount };
}

export function TimePricesEditor({
  windows,
  timeZone,
  defaultTimeZone,
  baseAmount,
  unitHint,
  onChange,
}: {
  windows: WindowDraft[];
  timeZone: string;
  /** 加第一段时预选的时区:这家已有规则用的时区(预填的 DeepSeek 是北京时间),否则本机时区。 */
  defaultTimeZone: string;
  baseAmount: string;
  /** 时段单价的单位,和规则的基础单价同一个(「USD / 百万输入 Token」)—— 时段只改金额,不改单位。 */
  unitHint: string;
  onChange: (next: { windows: WindowDraft[]; timeZone: string }) => void;
}) {
  const t = useI18n();
  const dayName = useWeekdayNames();
  const zoneOptions = useTimeZoneOptions(timeZone);
  const set = (index: number, patch: Partial<WindowDraft>) =>
    onChange({ timeZone, windows: windows.map((window, i) => (i === index ? { ...window, ...patch } : window)) });
  const toggleDay = (index: number, day: number) => {
    const days = windows[index].weekdays;
    const next = days.includes(day) ? days.filter((d) => d !== day) : [...days, day].sort((a, b) => a - b);
    // 一天都不选在后端的意思是「每天」—— 和用户点掉最后一天的本意正相反,所以不让点掉。
    if (next.length > 0) set(index, { weekdays: next });
  };

  return (
    <fieldset className="m-0 grid min-w-0 gap-2 border-0 p-0">
      <legend className="mb-2 p-0 text-ui-sm font-medium text-foreground">{t("pricingTimePrices")}</legend>
      <p className="m-0 text-ui-xs leading-[1.4] text-muted-foreground">{t("pricingTimePricesHint")}</p>
      {windows.length > 0 && (
        <label className={DIALOG_FIELD}>
          <span>{t("pricingTimeZone")}</span>
          <OptionPicker
            value={timeZone}
            ariaLabel={t("pricingTimeZone")}
            onChange={(zone) => onChange({ windows, timeZone: zone })}
            options={zoneOptions}
          />
        </label>
      )}
      {windows.map((window, index) => (
        <div key={index} className="grid gap-3 rounded-md border border-divider p-3" data-testid="pricing-time-window">
          {/* 每一格都要带标题:此前时间后面只有一个写着 0.000000 的框,看不出那是这段时间的单价,
              也看不出单位 —— 单位跟着规则走,写在框里。 */}
          {/* 三行:时间、这段时间的单价、适用的星期。弹窗只有这么宽,挤成一行时钟点和单位都被截断
              (「09…」「CNY / 百万输入…」),而这里每一个字都是要看清的。 */}
          <div className="grid grid-cols-[minmax(0,1fr)_auto] items-end gap-3">
            <div className={DIALOG_FIELD}>
              <span>{t("pricingTimeWindowTime")}</span>
              <div className="flex items-center gap-2">
                <TimePicker
                  className="w-36"
                  ariaLabel={t("pricingTimeWindowStart")}
                  value={window.start}
                  onChange={(start) => set(index, { start })}
                />
                <span className="text-muted-foreground" aria-hidden="true">–</span>
                <TimePicker className="w-36" ariaLabel={t("pricingTimeWindowEnd")} value={window.end} onChange={(end) => set(index, { end })} />
              </div>
            </div>
            <Button
              type="button"
              variant="ghost"
              className="size-10"
              aria-label={t("pricingTimeWindowRemove")}
              title={t("pricingTimeWindowRemove")}
              onClick={() => onChange({ timeZone: windows.length > 1 ? timeZone : "", windows: windows.filter((_, i) => i !== index) })}
            >
              <Trash2 size={14} />
            </Button>
          </div>
          <label className={DIALOG_FIELD}>
            <span>{t("pricingTimeWindowAmount")}</span>
            <span className="relative block">
              <Input
                type="number"
                min="0"
                step="0.000001"
                className="pr-40"
                aria-label={t("pricingTimeWindowAmount")}
                value={window.amount}
                placeholder="0.000000"
                onChange={(event) => set(index, { amount: event.target.value })}
              />
              <small className="pointer-events-none absolute right-3 top-1/2 max-w-36 -translate-y-1/2 truncate text-ui-xs text-muted-foreground">
                {unitHint}
              </small>
            </span>
          </label>
          <div className="grid gap-2">
            <span className="text-ui-xs text-muted-foreground">{t("pricingTimeWindowDays")}</span>
            <div className="flex flex-wrap items-center gap-1.5">
              {/* 常用的三种一键选;选中态用主色,不选的是描边 —— 此前两种状态几乎一个颜色,看不出选了哪几天。 */}
              {([["pricingEveryDay", ALL_DAYS], ["pricingWorkdays", WORKDAYS], ["pricingWeekends", WEEKENDS]] as const).map(([key, days]) => {
                const on = sameDays(window.weekdays, [...days]);
                return (
                  <Button
                    key={key}
                    type="button"
                    size="sm"
                    variant="outline"
                    aria-pressed={on}
                    className={on ? "border-primary/50 bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-primary" : "text-muted-foreground"}
                    onClick={() => set(index, { weekdays: [...days] })}
                  >
                    {t(key)}
                  </Button>
                );
              })}
              <span className="mx-1 h-5 w-px bg-divider" aria-hidden="true" />
              <div role="group" aria-label={t("pricingTimeWindowDays")} className="flex flex-wrap gap-1.5">
                {ALL_DAYS.map((day) => {
                  const on = window.weekdays.includes(day);
                  return (
                    <Button
                      key={day}
                      type="button"
                      size="sm"
                      variant="outline"
                      aria-pressed={on}
                      className={on ? "border-primary/50 bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-primary" : "text-muted-foreground"}
                      onClick={() => toggleDay(index, day)}
                    >
                      {dayName(day)}
                    </Button>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      ))}
      <AddRow
        label={t("pricingTimeWindowAdd")}
        onClick={() =>
          onChange({ windows: [...windows, nextWindow(windows, baseAmount)], timeZone: timeZone || defaultTimeZone })
        }
      />
    </fieldset>
  );
}
