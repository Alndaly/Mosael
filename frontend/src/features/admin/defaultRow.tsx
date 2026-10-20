import React from "react";
import { Star } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { AdminRowState } from "./adminLayout";

/**
 * 「默认」的摆放规则(维护者定的):**只出现在同一能力有多个可选实现的地方**,并且永远放在
 * 这些实现所在的那一节里 —— 节说明之后、实现列表之前。
 *
 * 为什么强调"节里":默认回答的是「在这几项之间选一个」。挪到别的页面、或者抽成一页「默认设置」,
 * 用户就看不到它在谁和谁之间选,只剩一个孤零零的当前值。
 *
 * 为什么强调"≥2 才出现":只有一种实现时,"默认"没有可选项,摆出来只是一句空话 —— 说清
 * 「这一节只有一种引擎,所以没有默认可设」比摆一个只能选它的控件有用。这个判据看的是**数据**
 * (列表长度),不是某个人记得在这里改一行代码。
 */

/** 这一节有没有"多个可选实现" —— 有,才谈得上默认。 */
export function hasDefaultChoice(optionCount: number | undefined): boolean {
  return optionCount !== undefined && optionCount >= 2;
}

/** 一句话:这一节只有一种实现,所以没有默认可设。 */
function OnlyOneImplementationNote() {
  const t = useI18n();
  return (
    <p data-admin-default-line data-default-kind="single" className="m-0 text-ui-xs leading-normal text-muted-foreground">
      {t("defaultOnlyOneEngine")}
    </p>
  );
}

/**
 * 一节里「默认」那一行。**这一行只读** —— 设默认的动作在各条实现自己那一行上(「设为默认」),
 * 所以默认只有一处可写,而且写的时候候选就摆在眼前。
 *
 * `optionCount` 还没取到(undefined)时什么都不画:"不知道有几个"不是"只有一个"。
 */
export function AdminDefaultLine({
  label,
  optionCount,
  current,
}: {
  label: string;
  /** 这一节的可选项数量;数据没到 = undefined。 */
  optionCount: number | undefined;
  /** 当前默认的那一项;没有默认时由调用方给一句「自动」之类。 */
  current?: React.ReactNode;
}) {
  const t = useI18n();
  if (optionCount === undefined) return null;
  if (!hasDefaultChoice(optionCount)) {
    return optionCount === 1 ? <OnlyOneImplementationNote /> : null;
  }
  return (
    <div
      data-admin-default-line
      data-default-kind="choice"
      className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1"
    >
      <span data-admin-default-label className="text-ui-xs leading-normal text-muted-foreground">
        {label}
      </span>
      <AdminRowState tone="success" icon={<Star size={13} aria-hidden />}>
        {current ?? t("defaultNotSet")}
      </AdminRowState>
    </div>
  );
}

/**
 * 只有一种实现的节用的那句话。和 `AdminDefaultLine` 同一个位置(说明之后、列表之前),
 * 免得"为什么这一节没有默认"要靠人猜。
 */
export function AdminOnlyOneNote({ optionCount }: { optionCount: number | undefined }) {
  return optionCount === 1 ? <OnlyOneImplementationNote /> : null;
}
