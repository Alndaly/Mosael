import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Asterisk, X } from "lucide-react";

import { fetchWorkflowTemplateChecks } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { AddRow } from "@/components/ui/add-row";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { OptionPicker } from "@/components/ui/option-picker";
import { cn } from "@/lib/utils";
import { objectFromRows, rowsFromObject } from "@/features/nodeForms/MapField";

/**
 * 开始节点的启动参数:一行一个参数 —— 名字、默认值、「必填」开关。
 *
 * 此前是两块:上面一张「名字 → 值或上游输出」的映射(和别的节点同一个控件),下面一个独立的「必填参数」文本框,
 * 手打逗号分隔的名字。同一个名字写两遍,打错了没有提示;参数改了名、删了行,那串字不跟着变,于是改名之后那一格
 * 永远是空的、删掉的参数还在必填里,运行前一直被拦。开始节点又没有上游,值那一格却是「值或上游输出」的下拉。
 *
 * 现在必填是**那一行自己的**:改名、删行时跟着走。存的形状不变 —— 参数仍是「名字 → 默认值」(`params`),必填仍是
 * 参数名的列表(`required_params`,后端 graph_rules._start_param_errors 按它查)。
 *
 * **选项参数**:声明了选项(`param_options`,参数名 → 选项列表)的那一行,默认值栏是下拉 —— 分析类模板的「数据来源」
 * 此前是手填的一格,用户得自己知道要打 `tikhub` 还是 `browser`,打错一个字静默走了浏览器。选项可以声明它要什么
 * (`requires`,模板前置条件的检查键):此刻没备好就在选项旁标「未就绪」(不禁选),选中了就在那一行说清 ——
 * 后端运行前按同一个判据拦(engine._check_chosen_options)。选项也跟着那一行走:改名、删行时一起变。
 *
 * 几格一起交出去(`onChange` 一次给全),撤销一步退回一次改动。
 *
 * **必填是一颗 ✱**,和行尾的删除同样大小、并排:点亮就是必填,悬停说是什么。必填又没有默认值的行不再另起一行
 * 字说「运行时要填」(每一行一句,几行下来满屏是同一句话),而是默认值那一格的占位直接写「运行时填」/「运行时选」。
 * 另起一行说的只剩真要改的:值不在选项里、选的那项没备好、名字空着(不会保存)、和前面重名(不会保存 —— 同名时
 * 先出现的那行算数,同 MapField)。
 */

export interface ParamOption {
  value: string;
  label: string;
  description?: string;
  /** 选它要备好什么:模板前置条件的检查键(后端 template_requirements.CHECKS)。 */
  requires?: string;
}

interface ParamRow {
  key: string;
  value: string;
  required: boolean;
  options?: ParamOption[];
}

export interface StartParams {
  params: Record<string, unknown>;
  required: string[];
  options: Record<string, ParamOption[]>;
}

function optionsOf(declared: unknown, name: string): ParamOption[] | undefined {
  if (!declared || typeof declared !== "object" || Array.isArray(declared)) return undefined;
  const list = (declared as Record<string, unknown>)[name];
  return Array.isArray(list) && list.length > 0 ? (list as ParamOption[]) : undefined;
}

function rowsFrom(params: unknown, required: unknown, options: unknown): ParamRow[] {
  const names = new Set(Array.isArray(required) ? required.filter((one): one is string => typeof one === "string") : []);
  return rowsFromObject(params).map((row) => ({ ...row, required: names.has(row.key), options: optionsOf(options, row.key) }));
}

/** 行 → 几格的值。名字空着、和前面重名的行不交出去(同 objectFromRows);必填按参数的顺序排;选项跟着那一行的名字。 */
export function startParamsFromRows(rows: ParamRow[]): StartParams {
  const params = objectFromRows(rows);
  const seen = new Set<string>();
  const required: string[] = [];
  const options: Record<string, ParamOption[]> = {};
  for (const row of rows) {
    const key = row.key.trim();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    if (row.required) required.push(key);
    if (row.options) options[key] = row.options;
  }
  return { params, required, options };
}

type Notice = "empty" | "duplicate" | "not-an-option" | "option-unavailable";

/** 这一行有什么要说的。`unavailable`:选项要的前置条件此刻没备好。 */
function rowNotice(rows: ParamRow[], index: number, unavailable: (option: ParamOption) => boolean): Notice | null {
  const row = rows[index];
  const key = row.key.trim();
  if (!key) return row.value.trim() || row.required ? "empty" : null;
  if (rows.slice(0, index).some((one) => one.key.trim() === key)) return "duplicate";
  const value = row.value.trim();
  if (row.options) {
    if (!value) return null;
    const chosen = row.options.find((one) => one.value === value);
    if (!chosen) return "not-an-option";
    return unavailable(chosen) ? "option-unavailable" : null;
  }
  return null;
}

export function StartParamsField({
  params,
  required,
  options,
  workspaceId,
  onChange,
}: {
  params: unknown;
  required: unknown;
  /** 选项参数(参数名 → 选项列表)。 */
  options: unknown;
  workspaceId: string;
  /** 几格一起交出去;`typing`:这一下是在打字(宿主可以把一串连发在撤销历史里塌成一条)。 */
  onChange: (next: StartParams, typing: boolean) => void;
}) {
  const t = useI18n();
  //: 本地留着行:「名字敲了一半」「两行暂时同名」「名字空着却勾了必填」在几格的值里都表示不出来(同 MapField)。
  const [rows, setRows] = React.useState<ParamRow[]>(() => rowsFrom(params, required, options));
  const signature = (next: StartParams) => JSON.stringify(next);
  const emitted = React.useRef(signature(startParamsFromRows(rowsFrom(params, required, options))));

  // 外面改了(撤销、智能体改图)才跟;自己发出去的那一版不跟,否则打字会被回流打断。
  React.useEffect(() => {
    const incoming = signature(startParamsFromRows(rowsFrom(params, required, options)));
    if (incoming === emitted.current) return;
    emitted.current = incoming;
    setRows(rowsFrom(params, required, options));
  }, [params, required, options]);

  //: 选项要的前置条件此刻齐没齐:和模板库同一个接口、同一份缓存。没有哪一项要东西时不问。
  const needsChecks = rows.some((row) => row.options?.some((one) => one.requires));
  const checks = useQuery({
    queryKey: ["workflow-template-checks", workspaceId],
    queryFn: () => fetchWorkflowTemplateChecks(workspaceId),
    enabled: needsChecks && Boolean(workspaceId),
    staleTime: 30_000,
  });
  const statusOf = new Map((checks.data ?? []).map((one) => [one.check, one.status]));
  //: 只有「确实缺」才标;还没测出来(unknown)、还没问到的不当成缺。
  const unavailable = (option: ParamOption) => Boolean(option.requires) && statusOf.get(option.requires!) === "missing";

  const push = (next: ParamRow[], typing: boolean) => {
    setRows(next);
    const values = startParamsFromRows(next);
    emitted.current = signature(values);
    onChange(values, typing);
  };
  const patchRow = (index: number, patch: Partial<ParamRow>, typing: boolean) =>
    push(rows.map((one, i) => (i === index ? { ...one, ...patch } : one)), typing);

  const noticeText = (notice: Notice, row: ParamRow): { text: string; tone: string } => {
    const chosen = row.options?.find((one) => one.value === row.value.trim());
    switch (notice) {
      case "empty":
        return { text: t("wfStartParamNameEmpty"), tone: "text-destructive" };
      case "duplicate":
        return { text: t("wfStartParamNameDuplicate"), tone: "text-destructive" };
      case "not-an-option":
        return { text: t("wfStartParamNotAnOption").replace("{value}", row.value.trim()), tone: "text-destructive" };
      case "option-unavailable":
        return { text: t("wfStartParamOptionUnavailable").replace("{label}", chosen?.label || row.value), tone: "text-destructive" };
    }
  };

  return (
    <div className="grid gap-1.5" data-start-params="">
      {rows.length > 0 && (
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_28px_28px] items-center gap-1 text-ui-2xs text-muted-foreground">
          <span>{t("wfStartParamName")}</span>
          <span>{t("wfStartParamDefault")}</span>
          {/* ✱ 和 × 两列不写表头:按钮自己悬停说是什么。 */}
          <span className="col-span-2" />
        </div>
      )}
      {rows.map((row, index) => {
        const notice = rowNotice(rows, index, unavailable);
        const name = row.key.trim() || t("wfStartParamUnnamed");
        const chosen = row.options?.find((one) => one.value === row.value.trim());
        return (
          <div className="grid gap-0.5" key={index} data-start-param-row={index}>
            <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_28px_28px] items-center gap-1">
              <Input
                size="sm"
                className="min-w-0 text-ui-xs"
                value={row.key}
                placeholder={t("wfStartParamName")}
                aria-label={t("wfStartParamName")}
                aria-invalid={notice === "empty" || notice === "duplicate" ? true : undefined}
                onChange={(event) => patchRow(index, { key: event.target.value }, true)}
              />
              {row.options ? (
                // 只能从几项里选:下拉。要的东西此刻没备好的那一项标「未就绪」,但照样能选 —— 备好它是用户下一步要做的事。
                <OptionPicker
                  size="sm"
                  className="min-w-0 text-ui-xs"
                  value={row.value.trim()}
                  ariaLabel={t("wfStartParamDefaultOf").replace("{name}", name)}
                  placeholder={row.required ? t("wfStartParamPickAtRun") : t("wfStartParamPick")}
                  options={row.options.map((one) => ({
                    value: one.value,
                    label: unavailable(one) ? `${one.label || one.value} · ${t("wfStartParamOptionNotReady")}` : one.label || one.value,
                    //: 选项的说明是数据(模板写的),下拉里只放纯文本 —— 和节点面板别的说明同一条出口。
                    description: one.description ? toPlainText(one.description) : undefined,
                  }))}
                  aria-invalid={notice === "not-an-option" ? true : undefined}
                  onChange={(next) => patchRow(index, { value: next }, false)}
                />
              ) : (
                // 开始节点是入口,没有上游:值就是一个默认值,不是「值或上游输出」的下拉。
                <Input
                  size="sm"
                  className="min-w-0 text-ui-xs"
                  value={row.value}
                  // 必填又没有默认值:运行时要填 —— 写在占位里,不另起一行字。
                  placeholder={row.required ? t("wfStartParamAskAtRun") : t("wfStartParamDefaultPlaceholder")}
                  aria-label={t("wfStartParamDefaultOf").replace("{name}", name)}
                  onChange={(event) => patchRow(index, { value: event.target.value }, true)}
                />
              )}
              <IconButton
                variant="ghost"
                size="icon-xs"
                label={t("wfStartParamRequiredOf").replace("{name}", name)}
                hint={row.required ? t("wfStartParamRequiredOn") : t("wfStartParamRequiredOff")}
                aria-pressed={row.required}
                data-start-param-required={row.required ? "" : undefined}
                className={cn(!row.required && "text-muted-foreground/45 hover:text-muted-foreground")}
                onClick={() => patchRow(index, { required: !row.required }, false)}
              >
                <Asterisk size={13} strokeWidth={row.required ? 2.75 : 2} />
              </IconButton>
              <IconButton
                variant="ghost"
                size="icon-xs"
                label={t("wfStartParamRemove").replace("{name}", name)}
                onClick={() => push(rows.filter((_, i) => i !== index), false)}
              >
                <X size={12} />
              </IconButton>
            </div>
            {notice ? (
              <small className={noticeText(notice, row).tone} data-start-param-notice={notice}>
                {noticeText(notice, row).text}
              </small>
            ) : chosen?.description ? (
              // 选中的那一项说一句它意味着什么(要配什么、取舍在哪)—— 下拉收起来之后也看得见。
              <small className="text-muted-foreground" data-start-param-option-note="">
                <InlineMarkdown text={chosen.description} />
              </small>
            ) : null}
          </div>
        );
      })}
      <AddRow dense label={t("wfMapAdd")} onClick={() => push([...rows, { key: "", value: "", required: false }], false)} />
    </div>
  );
}
