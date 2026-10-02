import React from "react";
import { X } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { AddRow } from "@/components/ui/add-row";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { objectFromRows, rowsFromObject } from "@/features/nodeForms/MapField";

/**
 * 开始节点的启动参数:一行一个参数 —— 名字、默认值、「必填」开关。
 *
 * 此前是两块:上面一张「名字 → 值或上游输出」的映射(和别的节点同一个控件),下面一个独立的「必填参数」文本框,
 * 手打逗号分隔的名字。同一个名字写两遍,打错了没有提示;参数改了名、删了行,那串字不跟着变,于是改名之后那一格
 * 永远是空的、删掉的参数还在必填里,运行前一直被拦。开始节点又没有上游,值那一格却是「值或上游输出」的下拉。
 *
 * 现在必填是**那一行自己的**:改名、删行时跟着走。存的形状不变 —— 参数仍是「名字 → 默认值」(`params`),必填仍是
 * 参数名的列表(`required_params`,后端 graph_rules._start_param_errors 按它查)。两格一起交出去(`onChange` 一次给全),
 * 撤销一步退回一次改动。
 *
 * 就地说清的几件事:必填却没有默认值的行(运行时要填);名字空着的行(不会保存);和前面重名的行(不会保存 ——
 * 同名时先出现的那行算数,同 MapField)。
 */

interface ParamRow {
  key: string;
  value: string;
  required: boolean;
}

function rowsFrom(params: unknown, required: unknown): ParamRow[] {
  const names = new Set(Array.isArray(required) ? required.filter((one): one is string => typeof one === "string") : []);
  return rowsFromObject(params).map((row) => ({ ...row, required: names.has(row.key) }));
}

/** 行 → 两格的值。名字空着、和前面重名的行不交出去(同 objectFromRows);必填按参数的顺序排。 */
export function startParamsFromRows(rows: ParamRow[]): { params: Record<string, unknown>; required: string[] } {
  const params = objectFromRows(rows);
  const seen = new Set<string>();
  const required: string[] = [];
  for (const row of rows) {
    const key = row.key.trim();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    if (row.required) required.push(key);
  }
  return { params, required };
}

/** 这一行有什么要说的:名字空着 / 和前面重名 / 必填却没有默认值。 */
function rowNotice(rows: ParamRow[], index: number): "empty" | "duplicate" | "ask-at-run" | null {
  const row = rows[index];
  const key = row.key.trim();
  if (!key) return row.value.trim() || row.required ? "empty" : null;
  if (rows.slice(0, index).some((one) => one.key.trim() === key)) return "duplicate";
  if (row.required && !row.value.trim()) return "ask-at-run";
  return null;
}

export function StartParamsField({
  params,
  required,
  onChange,
}: {
  params: unknown;
  required: unknown;
  /** 两格一起交出去;`typing`:这一下是在打字(宿主可以把一串连发在撤销历史里塌成一条)。 */
  onChange: (next: { params: Record<string, unknown>; required: string[] }, typing: boolean) => void;
}) {
  const t = useI18n();
  //: 本地留着行:「名字敲了一半」「两行暂时同名」「名字空着却勾了必填」在两格的值里都表示不出来(同 MapField)。
  const [rows, setRows] = React.useState<ParamRow[]>(() => rowsFrom(params, required));
  const signature = (next: { params: Record<string, unknown>; required: string[] }) => JSON.stringify(next);
  const emitted = React.useRef(signature(startParamsFromRows(rowsFrom(params, required))));

  // 外面改了(撤销、智能体改图)才跟;自己发出去的那一版不跟,否则打字会被回流打断。
  React.useEffect(() => {
    const incoming = signature(startParamsFromRows(rowsFrom(params, required)));
    if (incoming === emitted.current) return;
    emitted.current = incoming;
    setRows(rowsFrom(params, required));
  }, [params, required]);

  const push = (next: ParamRow[], typing: boolean) => {
    setRows(next);
    const values = startParamsFromRows(next);
    emitted.current = signature(values);
    onChange(values, typing);
  };
  const patchRow = (index: number, patch: Partial<ParamRow>, typing: boolean) =>
    push(rows.map((one, i) => (i === index ? { ...one, ...patch } : one)), typing);

  const NOTICE = {
    empty: { text: t("wfStartParamNameEmpty"), tone: "text-destructive" },
    duplicate: { text: t("wfStartParamNameDuplicate"), tone: "text-destructive" },
    "ask-at-run": { text: t("wfStartParamAskAtRun"), tone: "text-warning" },
  } as const;

  return (
    <div className="grid gap-1.5" data-start-params="">
      {rows.length > 0 && (
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_auto_24px] items-center gap-1 text-ui-2xs text-muted-foreground">
          <span>{t("wfStartParamName")}</span>
          <span>{t("wfStartParamDefault")}</span>
          <span>{t("wfStartParamRequired")}</span>
          <span />
        </div>
      )}
      {rows.map((row, index) => {
        const notice = rowNotice(rows, index);
        const name = row.key.trim() || t("wfStartParamUnnamed");
        return (
          <div className="grid gap-0.5" key={index} data-start-param-row={index}>
            <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_auto_24px] items-center gap-1">
              <Input
                size="sm"
                className="min-w-0 text-ui-xs"
                value={row.key}
                placeholder={t("wfStartParamName")}
                aria-label={t("wfStartParamName")}
                aria-invalid={notice === "empty" || notice === "duplicate" ? true : undefined}
                onChange={(event) => patchRow(index, { key: event.target.value }, true)}
              />
              {/* 开始节点是入口,没有上游:值就是一个默认值,不是「值或上游输出」的下拉。 */}
              <Input
                size="sm"
                className="min-w-0 text-ui-xs"
                value={row.value}
                placeholder={t("wfStartParamDefaultPlaceholder")}
                aria-label={t("wfStartParamDefaultOf").replace("{name}", name)}
                onChange={(event) => patchRow(index, { value: event.target.value }, true)}
              />
              <span className="grid w-8 place-items-center">
                <Checkbox
                  checked={row.required}
                  aria-label={t("wfStartParamRequiredOf").replace("{name}", name)}
                  onCheckedChange={(checked) => patchRow(index, { required: checked === true }, false)}
                />
              </span>
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label={t("wfStartParamRemove").replace("{name}", name)}
                onClick={() => push(rows.filter((_, i) => i !== index), false)}
              >
                <X size={12} />
              </Button>
            </div>
            {notice && (
              <small className={NOTICE[notice].tone} data-start-param-notice={notice}>
                {NOTICE[notice].text}
              </small>
            )}
          </div>
        );
      })}
      <AddRow dense label={t("wfMapAdd")} onClick={() => push([...rows, { key: "", value: "", required: false }], false)} />
    </div>
  );
}
