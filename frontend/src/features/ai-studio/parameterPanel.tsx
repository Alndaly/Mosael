import React from "react";
import type { LucideIcon } from "lucide-react";

import { InspectorCard } from "@/components/layout/InspectorCard";

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
  children,
}: {
  label: string;
  /** 控件下面那句解释。可省 —— 不必为每一栏硬凑一句。 */
  hint?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <label className="grid gap-1.5 text-ui-sm text-muted-foreground">
      <span>{label}</span>
      {children}
      {hint != null && <span className="text-ui-2xs leading-[1.45] text-muted-foreground">{hint}</span>}
    </label>
  );
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
