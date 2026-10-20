import React from "react";

import { useI18n } from "@/app/preferences";
import { SETTINGS_FIELD_WIDTH } from "@/components/settings/settings-layout";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ADMIN_CARD, AdminRow, AdminTag } from "./adminLayout";

/**
 * 「默认」的摆放规则(维护者定的):**只出现在同一能力有多个可选实现的地方**,并且永远放在
 * 这些实现所在的那一节里 —— 节说明之后、实现列表之前。**设默认的控件只有这一处**;列表行
 * 只负责下载/状态,不再承担"设默认"(那边只剩名字右边一枚不可点的「当前默认」badge)。
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
 *
 * 为什么是**整行**:默认不是飘在节顶的一枚小标签,它和列表行、和「模型下载源」那一行是同一种
 * 东西 —— `AdminRow` 装在同一张 `ADMIN_CARD` 里:左边标题 + 一句说明,右边才是控件。只有一种
 * 实现时也一样,只是右边没有控件、说明换成「这一节只有一种引擎」。
 */

/** 这一节有没有"多个可选实现" —— 有,才谈得上默认。 */
export function hasDefaultChoice(optionCount: number | undefined): boolean {
  return optionCount !== undefined && optionCount >= 2;
}

/** 一句话:这一节只有一种实现,所以没有默认可设。 */
function OnlyOneImplementationRow({ label }: { label: string }) {
  const t = useI18n();
  return (
    <div className={ADMIN_CARD} data-admin-default-line data-default-kind="single">
      <AdminRow label={label} description={t("defaultOnlyOneEngine")} />
    </div>
  );
}

/** 选择器里的一项。`installed` 决定它能不能被选中 —— 没装的设成默认只是一句空话(后端也会拒)。
 *  `reason` 是禁用时给的那句理由:默认是「还没安装,先下载」;不要下载、只是这台机器上用不了的
 *  (比如 ffmpeg 不带 RNNoise 滤镜)要给它真正的原因,不然用户会去找一个不存在的下载按钮。 */
export type AdminDefaultOption = {
  id: string;
  label: string;
  installed: boolean;
  reason?: string;
};

/**
 * 一节里「默认」那**一整行**:说明之后、列表之前,和「模型下载源」同款的一整张卡片 + 一行。
 *
 * 这是整节里**唯一**能改默认的地方 —— 列表行上的「设为默认」已经拿掉,否则同一个默认就有
 * 两个写入口。`options` 还没取到(undefined)时什么都不画:"不知道有几个"不是"只有一个"。
 *
 * 说明默认是一句通用的话(「只影响这台机器」「这里唯一能改」);某一节还有额外的一层
 * (降噪:按人选的覆盖它),调用处用 `description` 写清 —— 别让用户以为这里设了就一定生效。
 */
export function AdminDefaultSelect({
  label,
  description,
  options,
  value,
  placeholder,
  onChange,
  disabled,
}: {
  label: string;
  /** 行说明;不给就用那句通用的 `defaultRowHint`。 */
  description?: string;
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
    return count === 1 ? <OnlyOneImplementationRow label={label} /> : null;
  }
  return (
    <div className={ADMIN_CARD} data-admin-default-line data-default-kind="choice">
      <AdminRow label={label} description={description ?? t("defaultRowHint")}>
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
                description={option.installed ? undefined : (option.reason ?? t("defaultNotInstalled"))}
              >
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </AdminRow>
    </div>
  );
}

/**
 * 列表里**已经默认**的那一行上的 badge:贴着名字(标题)的右边,不可点 —— 改默认在节顶那个选择器里。
 * 和「设为默认」按钮不同,它不承担动作,所以也不会成为第二个写入口。
 *
 * **为什么离开右边那一格**:右边回答的是"这一项现在能不能用"(已安装 / 可用 / 下载),而这枚
 * 回答的是"这几项里选中的是它" —— 两件事并排放在同一格,读起来像同一类状态。维护者原话:
 * 「这种当前默认的提示请你放在左侧 title 的右边,可以做成一个 badge 的样式」。
 *
 * **为什么是 `AdminTag` 药丸、为什么只有字**:形状和降噪那节的「会去掉音乐」是同一枚 —— 全圆、
 * 11px、淡底、不描边。字就是「当前默认」本身 —— 一颗星得靠猜,而读屏也只念得出字。
 *
 * **为什么同形状、不同色**:维护者要的是「不同类型的提示用不同的 badge 配色」。「会去掉音乐」是
 * **代价提醒**,用 `warning`(暖色);「当前默认」是**正向选中**,用新档 `positive` —— 走现成的
 * `--success` token,同样 14% 淡底,不新造颜色。两种淡底都落在 `ADMIN_CARD`(`bg-panel`)上,
 * 按 tokens.css 的数值算过:亮 4.75:1、暗 6.49:1(半透明卡片模式下 4.70 / 6.77),都过 4.5:1。
 * 颜色只回答语义;它仍然不可点(不包按钮),测试按 `data-admin-default-marker` 找它。
 */
export function AdminDefaultMarker() {
  const t = useI18n();
  //: 锚点挂在外层:AdminTag 保持通用药丸(只认 tone),不为了这枚标记给它另开口子。
  return (
    <span data-admin-default-marker className="inline-flex shrink-0">
      <AdminTag tone="positive">{t("defaultCurrent")}</AdminTag>
    </span>
  );
}

/**
 * 只有一种实现的节用的那一行。和 `AdminDefaultSelect` 同一个位置(说明之后、列表之前),
 * 也同一种整行样子 —— 免得"为什么这一节没有默认"要靠人猜,又和别的行长得不一样。
 * 调用处不给标题时就用一个中性的「默认」。
 */
export function AdminOnlyOneNote({ optionCount, label }: { optionCount: number | undefined; label?: string }) {
  const t = useI18n();
  return optionCount === 1 ? <OnlyOneImplementationRow label={label ?? t("defaultRowTitle")} /> : null;
}
