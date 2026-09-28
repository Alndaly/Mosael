import React from "react";
import type { LucideIcon } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { InspectorCard } from "@/components/layout/InspectorCard";
import { Input } from "@/components/ui/input";
import { OptionPicker, type PickerOption } from "@/components/ui/option-picker";
import { Textarea } from "@/components/ui/textarea";
import type { DeclaredParameter } from "@/lib/generationCapabilities";

/**
 * 「引擎参数」侧栏的排版词汇 —— 和对话页右侧的智能体检查器共用一套壳(InspectorCard)。
 *
 * 此前这一栏是十几个平铺的 `<label>`:模型、尺寸、张数、seed、反向提示词、首尾帧、各家自定义的
 * 开关和枚举,全都同一个分量、同一个间距,从上到下一路排下去。于是"这个模型出多大"和
 * "vendor 自己加的那个 enum"看上去一样重,而找一个参数只能一行行扫。
 *
 * 分成几块之后,标题行本身就是路标:先看块名、再在块里找那一栏。块的外壳直接用检查器那一个,
 * 不新发明 —— 两个侧栏在同一个应用的同一侧,长得不一样没有任何理由。
 */

/**
 * 参数面板里控件统一的样子。
 *
 * 三件事在这儿定死,因为此前它们在十三处各写各的:**高度**收到 h-8(表单默认的 h-10 在侧栏里
 * 一屏放不下几栏);**底色**统一 `bg-field` —— 此前 Select 是 field(浅色下是白)、Input 却被
 * 改成了 control(面板色),同一行里两种填充,而它们是同一类控件;**焦点**回到全局那一套
 * `ring-ring`,不再让 Input 单独走一套 primary 描边。
 */
export const PARAMETER_CONTROL_CLASS =
  "h-8 w-full min-w-0 rounded-lg border-border bg-field px-2.5 text-ui-sm font-medium text-foreground";

/**
 * 一栏参数:上标签、下控件。
 *
 * 标签用次级色、控件里的值用前景色 —— 和检查器里的 InspectorRow 同一个说法(左标签次级、
 * 右值前景),只是竖过来:参数名有「反向提示词」这种五个字的,64px 的标签列装不下。
 */
export function ParameterField({
  label,
  hint,
  title,
  children,
}: {
  label: string;
  /** 控件下面那句解释。可省 —— 不必为每一栏硬凑一句。 */
  hint?: React.ReactNode;
  /** 悬停在标签上看到的那句(原始的「节点 · 输入名」这类排错用的字,不值得占一行)。 */
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="grid gap-1.5 text-ui-sm text-muted-foreground">
      <span title={title}>{label}</span>
      {children}
      {hint != null && <span className="text-ui-2xs leading-[1.45] text-muted-foreground">{hint}</span>}
    </label>
  );
}

/**
 * 一行参数:**标签在左、控件在右;弹层窄了就上下叠**。设置弹层(画板的生成参数)用它。
 *
 * 此前是写死的 `112px | 1fr` 两列:参数名一长(`CheckpointLoaderSimple · ckpt_name`)就折成两行,
 * 再长就溢进控件那一列。现在两件事一起兜住:
 *
 * - 标签**单行截断**,全名在悬停提示里(`title`)—— 两列时每一行一样高,扫一眼对得齐;
 * - 按**容器**宽度而不是视口宽度决定两列还是上下叠(容器查询):同一个弹层放在窄的节点旁边、
 *   或者被挤窄时,标签到控件上面去,控件拿满整行,不会只剩一小截。
 */
export function ParameterRow({
  label,
  title,
  children,
}: {
  label: string;
  /** 悬停在标签上看到的全文。不给就是标签本身(截断之后得有地方看全)。 */
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="@container/parameter-row min-w-0">
      <div className="grid min-w-0 gap-1.5 @[280px]/parameter-row:grid-cols-[112px_minmax(0,1fr)] @[280px]/parameter-row:items-center @[280px]/parameter-row:gap-3">
        <span data-slot="parameter-label" className="min-w-0 truncate text-ui-xs text-muted-foreground" title={title || label}>
          {label}
        </span>
        {children}
      </div>
    </div>
  );
}

/**
 * 模型自己声明的一个下拉参数:有哪些选项、此刻显示哪一项、选了之后存什么。
 * AI 工作台、画板、工作流节点三处共用 —— 各写一遍的话,「默认」怎么说就会有三种说法。
 *
 * **模型的默认值就是列表里的那一项**,旁边标一句「默认」,而不是在最前面另加一项
 * 「默认(euler)」:那种写法让同一个值在列表里出现两次,而且读起来像是一个叫「默认」的采样器。
 * 选中默认那一项 = 不设(不发,ADR 0015);默认值不在可选值里(或者没有默认值)时才另加一项。
 */
export function declaredChoices(
  parameter: DeclaredParameter,
  t: (key: "genDeclaredDefaultHint" | "genDeclaredDefaultNone" | "wfGenToggleOn" | "wfGenToggleOff") => string,
): { options: PickerOption[]; shown: (stored: string) => string; stored: (picked: string) => string } {
  const fallback = parameter.defaultValue === undefined ? "" : String(parameter.defaultValue);
  const base: PickerOption[] =
    parameter.type === "boolean"
      ? [
          { value: "true", label: t("wfGenToggleOn") },
          { value: "false", label: t("wfGenToggleOff") },
        ]
      : parameter.options.map((option) => ({ value: option, label: option }));
  const listed = fallback !== "" && base.some((option) => option.value === fallback);
  const marked = base.map((option) =>
    listed && option.value === fallback ? { ...option, description: t("genDeclaredDefaultHint") } : option,
  );
  const options = listed
    ? marked
    : [
        {
          value: DEFAULT_CHOICE,
          label: fallback || t("genDeclaredDefaultNone"),
          description: fallback ? t("genDeclaredDefaultHint") : undefined,
        },
        ...marked,
      ];
  return {
    options,
    shown: (stored) => stored || (listed ? fallback : DEFAULT_CHOICE),
    stored: (picked) => (picked === DEFAULT_CHOICE || (listed && picked === fallback) ? "" : picked),
  };
}

/**
 * 一块参数。**空了就整块不渲染** —— 这是它存在的理由。
 *
 * 每一栏都挂着 `supportsParameter(...)` 之类的条件:换一个模型,一块里可能一栏都不剩。
 * 光秃秃的标题行比没有更糟 —— 它宣告"这里有东西"然后什么都不给。
 *
 * 判空只能在 JS 里做:CSS 的 `:empty` / 相邻兄弟选择器看到的是渲染后的 DOM,而
 * `{cond && <Field/>}` 为假时连节点都不产生,`:empty` 又会被空白文本节点破坏。
 */
export function ParameterSection({
  icon,
  title,
  children,
}: {
  icon: LucideIcon;
  title: string;
  children: React.ReactNode;
}) {
  // toArray 会丢掉 null/undefined/布尔,正好就是那些条件渲染为假的栏。
  const fields = React.Children.toArray(children);
  if (fields.length === 0) return null;
  return (
    <InspectorCard icon={icon} title={title}>
      {fields}
    </InspectorCard>
  );
}


/**
 * 模型**自己声明的**一个参数(`parameter_schema`,见 lib/generationCapabilities.declaredParameters)的控件。
 *
 * 值存的是控件里的原文,空串 = 没动过(不发)。插件给的默认值只当占位 / 标着「默认」的那一项,
 * 不替用户提交 —— 那是模型自己的默认,不是用户的选择(ADR 0015)。下拉的说法见 declaredChoices。
 */
export function DeclaredParameterControl({
  parameter,
  value,
  onChange,
}: {
  parameter: DeclaredParameter;
  value: string;
  onChange: (next: string) => void;
}) {
  const t = useI18n();
  const fallback = parameter.defaultValue === undefined ? "" : String(parameter.defaultValue);
  if (parameter.type === "boolean" || parameter.options.length > 0) {
    const choices = declaredChoices(parameter, t);
    return (
      <OptionPicker
        value={choices.shown(value)}
        onChange={(next) => onChange(choices.stored(next))}
        options={choices.options}
        className={PARAMETER_CONTROL_CLASS}
      />
    );
  }
  if (parameter.multiline) {
    return (
      <Textarea
        className="min-h-20 rounded-lg border-border bg-field text-ui-sm text-foreground"
        value={value}
        placeholder={fallback}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }
  const numeric = parameter.type === "integer" || parameter.type === "number";
  return (
    <Input
      className={PARAMETER_CONTROL_CLASS}
      type={numeric ? "number" : "text"}
      min={parameter.minimum}
      max={parameter.maximum}
      step={parameter.step ?? (numeric ? "any" : undefined)}
      value={value}
      placeholder={fallback || t("genDeclaredDefaultNone")}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

/** 「默认」那一项的值。空串不能当 Select 的值,所以借一个不会和真实选项撞上的哨兵。 */
export const DEFAULT_CHOICE = "__model_default__";
