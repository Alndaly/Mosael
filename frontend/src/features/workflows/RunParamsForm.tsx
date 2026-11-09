import React from "react";

import { useI18n } from "@/app/preferences";
import { Input } from "@/components/ui/input";
import { OptionPicker } from "@/components/ui/option-picker";
import { Truncate } from "@/components/ui/truncate";
import type { StartParamSpec } from "./runParams";

/** 空着的选项参数「跟着默认值走」,和输入框空着同一个意思。 */
const USE_DEFAULT = "\u0000default";

/**
 * 一次运行带给工作流的参数(定时任务存着的、点运行时当场填的):开始节点的每一项一行。空着就用工作流里的默认值
 * (写在占位里);必填又没有默认值的,不填就跑不起来,`showMissing` 时在那一行说出来。选项参数是下拉。
 * `hint`:格子下面那句说明 —— 定时任务说「到点按这里填的跑」,点运行说「只带给这一次」。
 */
export function RunParamsForm({
  specs,
  values,
  onChange,
  showMissing,
  missing,
  hint,
}: {
  specs: StartParamSpec[];
  values: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
  showMissing: boolean;
  missing: string[];
  hint: string;
}) {
  const t = useI18n();
  if (specs.length === 0) return null;
  const set = (name: string, value: string) => onChange({ ...values, [name]: value });
  return (
    <div className="grid gap-2" data-task-params="">
      <span className="text-xs font-semibold text-foreground">{t("taskParamsLabel")}</span>
      <div className="grid gap-2">
        {specs.map((spec) => {
          const fallback = spec.fallback === undefined || spec.fallback === null ? "" : String(spec.fallback);
          const isMissing = showMissing && missing.includes(spec.name);
          const label = `${spec.name}${spec.required ? " *" : ""}`;
          return (
            <label key={spec.name} className="grid grid-cols-[minmax(0,140px)_minmax(0,1fr)] items-center gap-x-3 gap-y-1">
              <Truncate className="text-ui-sm text-foreground">{label}</Truncate>
              {spec.options ? (
                <OptionPicker
                  value={values[spec.name] || USE_DEFAULT}
                  onChange={(next) => set(spec.name, next === USE_DEFAULT ? "" : next)}
                  ariaLabel={label}
                  options={[
                    {
                      value: USE_DEFAULT,
                      label: fallback ? t("taskParamUseDefault").replace("{value}", spec.options.find((one) => one.value === fallback)?.label || fallback) : t("taskParamPick"),
                    },
                    ...spec.options.map((one) => ({ value: one.value, label: one.label || one.value })),
                  ]}
                  className="w-full"
                />
              ) : (
                <Input
                  value={values[spec.name] ?? ""}
                  aria-label={label}
                  aria-invalid={isMissing || undefined}
                  placeholder={fallback ? t("taskParamDefaultPlaceholder").replace("{value}", fallback) : spec.required ? t("taskParamRequiredPlaceholder") : ""}
                  onChange={(event) => set(spec.name, event.target.value)}
                />
              )}
              {isMissing && <small className="col-start-2 text-ui-xs text-destructive">{t("taskParamMissing")}</small>}
            </label>
          );
        })}
      </div>
      <small className="text-ui-xs leading-[1.5] text-muted-foreground">{hint}</small>
    </div>
  );
}
