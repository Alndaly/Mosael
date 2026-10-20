import React from "react";
import { Star } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { SETTINGS_FIELD_WIDTH } from "@/components/settings/settings-layout";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

/**
 * 「默认」的摆放规则(维护者定的):**只出现在同一能力有多个可选实现的地方**,并且永远放在
 * 这些实现所在的那一节里 —— 节说明之后、实现列表之前。**设默认的控件只有这一处**;列表行
 * 只负责下载/状态,不再承担"设默认"(那边只剩一枚不可点的「当前默认」)。
 *
 * 为什么强调"节里":默认回答的是「在这几项之间选一个」。挪到别的页面、或者抽成一页「默认设置」,
 * 用户就看不到它在谁和谁之间选,只剩一个孤零零的当前值。
 *
 * 为什么强调"≥2 才出现":只有一种实现时,"默认"没有可选项,摆出来只是一句空话 —— 说清
 * 「这一节只有一种引擎,所以没有默认可设」比摆一个只能选它的控件有用。这个判据看的是**数据**
 * (列表长度),不是某个人记得在这里改一行代码。
 *
 * 为什么是**下拉**而不是一组单选按钮:转写那一节目录里有五个模型(还会长),单选按钮会把
 * 同一批名字在列表正上方再抄一遍 —— 那正是维护者说的"设置与列表混在一起";下拉只占一行,
 * 当前值在触发器里,候选在弹层里。未安装的选项在弹层里禁用,并带一行理由("还没安装,先下载"),
 * 不必猜为什么点不了。两三个选项的克隆组沿用同一个控件,这一页就只有一种设默认的样子。
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

/** 选择器里的一项。`installed` 决定它能不能被选中 —— 没装的设成默认只是一句空话(后端也会拒)。 */
export type AdminDefaultOption = {
  id: string;
  label: string;
  installed: boolean;
};

/**
 * 一节里「默认」那**一行控件**:说明之后、列表之前。
 *
 * 这是整节里**唯一**能改默认的地方 —— 列表行上的「设为默认」已经拿掉,否则同一个默认就有
 * 两个写入口。`options` 还没取到(undefined)时什么都不画:"不知道有几个"不是"只有一个"。
 */
export function AdminDefaultSelect({
  label,
  options,
  value,
  placeholder,
  onChange,
  disabled,
}: {
  label: string;
  /** 这一节的可选项;数据没到 = undefined。 */
  options: AdminDefaultOption[] | undefined;
  /** 当前默认的那一项;没有默认时留空。 */
  value?: string;
  /** 没有默认时触发器里那句话。 */
  placeholder?: string;
  /** 选中一个能选的实现。 */
  onChange: (id: string) => void;
  /** 写入还在路上时先别让人再点一次。 */
  disabled?: boolean;
}) {
  const t = useI18n();
  if (!options) return null;
  const count = options.length;
  if (!hasDefaultChoice(count)) {
    return count === 1 ? <OnlyOneImplementationNote /> : null;
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
      <Select value={value ?? ""} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger aria-label={label} className={SETTINGS_FIELD_WIDTH}>
          <SelectValue placeholder={placeholder ?? t("defaultNotSet")} />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem
              key={option.id}
              value={option.id}
              disabled={!option.installed}
              /* 禁用了就要说清为什么 —— 一个灰掉、没有理由的选项,看起来只是"点了没反应"。 */
              description={option.installed ? undefined : t("defaultNotInstalled")}
            >
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

/**
 * 列表里**已经默认**的那一行上的淡标记。只是一行字,不可点 —— 改默认在节顶那个选择器里。
 * 和「设为默认」按钮不同,它不承担动作,所以也不会成为第二个写入口。
 */
export function AdminDefaultMarker() {
  const t = useI18n();
  return (
    <span
      data-admin-default-marker
      className="inline-flex items-center gap-1 text-ui-xs leading-normal text-muted-foreground"
    >
      <Star size={12} aria-hidden />
      {t("defaultCurrent")}
    </span>
  );
}

/**
 * 只有一种实现的节用的那句话。和 `AdminDefaultSelect` 同一个位置(说明之后、列表之前),
 * 免得"为什么这一节没有默认"要靠人猜。
 */
export function AdminOnlyOneNote({ optionCount }: { optionCount: number | undefined }) {
  return optionCount === 1 ? <OnlyOneImplementationNote /> : null;
}
