import type React from "react";
import { ListChecks, X } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";

/**
 * 列表批量选择的**界面那一半**:行首勾选框、操作条、「选择」入口。状态机在 lib/useMultiSelect。
 *
 * **为什么要有**:设置里那些列表(成本规则、模型、供应商)只能一行一行删。按目录预填一次能生成
 * 几十条价格规则,发现填错了就得点几十次垃圾桶,每次还各弹一次确认——用户的动作是"把这一批去掉",
 * 而界面只提供"去掉这一个"。
 */

/** 行首的勾选框。点它不该触发行本身的点击(编辑、展开),所以就地拦掉。 */
export function BulkCheckbox({
  checked,
  onToggle,
  label,
  className,
}: {
  checked: boolean;
  onToggle: (event: { shiftKey?: boolean }) => void;
  label: string;
  className?: string;
}) {
  return (
    <span
      className={cn("grid h-7 w-7 shrink-0 place-items-center", className)}
      onClick={(event) => {
        event.stopPropagation();
        onToggle({ shiftKey: event.shiftKey });
      }}
    >
      <Checkbox checked={checked} aria-label={label} />
    </span>
  );
}

/**
 * 选中后浮出来的操作条。
 *
 * **一直占位 vs 选中才出现**:选中才出现——列表在没有选中时是纯浏览态,常驻一条空工具条会让
 * 每个列表都先矮一截。出现时它接管的是"对这一批做什么",所以计数、全选、动作、退出选择在一起。
 */
export function BulkActionBar({
  active,
  count,
  allSelected,
  onToggleAll,
  onExit,
  children,
}: {
  active: boolean;
  count: number;
  allSelected: boolean;
  onToggleAll: () => void;
  onExit: () => void;
  children?: React.ReactNode;
}) {
  const t = useI18n();
  // 进了选择模式就一直在:一个都没选时它是"全选"和"退出"的唯一出口,
  // 等选中了才出现的话,用户点开选择模式会看到一个没有出口的界面。
  if (!active) return null;
  return (
    // 按钮尺寸在这里统一定,而不是让四个调用方各写各的 —— 同一条操作条在不同列表里
    // 高低不一是最容易漏掉的那种不一致。11.5px 与列表行的次要文字同级,32px 的 sm 按钮
    // 会把这条工具条顶得比它统领的行还高。
    //
    // **必须排除勾选框**:Radix 的 Checkbox 根节点也是个 <button>,不排除的话它会一起吃到
    // h-7 和 px-2,15px 见方的框被撑成一条竖杠。
    <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-primary/35 bg-[color-mix(in_srgb,var(--primary)_6%,transparent)] px-2 py-1 [&_button:not([role=checkbox])]:h-7 [&_button:not([role=checkbox])]:gap-1 [&_button:not([role=checkbox])]:px-2 [&_button:not([role=checkbox])]:text-ui-xs">
      {/* 和行首勾选框走**同一个 28px 居中盒子**:行里的勾选框是 BulkCheckbox 那个 h-7 w-7
          的格子,直接放一个裸 Checkbox 会比下面每一行都靠左约 6px —— 一列本该对齐的东西
          错开半个字宽,比错开一大截更显眼。 */}
      <span className="grid h-7 w-7 shrink-0 place-items-center">
        {/* 只选了一部分时画横杠 —— 这个框既是"全选"按钮也是"选了多少"的状态,
            在半选时显示成未勾会让人以为刚才的勾选没生效。 */}
        <Checkbox
          checked={allSelected ? true : count > 0 ? "indeterminate" : false}
          aria-label={allSelected ? t("bulkDeselectAll") : t("bulkSelectAll")}
          onCheckedChange={() => onToggleAll()}
        />
      </span>
      <span className="text-ui-sm font-medium text-foreground">
        {count > 0 ? t("bulkSelectedCount").replace("{n}", String(count)) : t("bulkSelectNone")}
      </span>
      <span className="min-w-4 flex-1" />
      {/* 一个都没选时,动作按钮全部禁用而不是消失 —— 消失会让人以为这个模式没做完。 */}
      {count > 0 && children}
      <Button variant="ghost" size="sm" onClick={onExit}>
        <X size={12} /> {t("bulkExit")}
      </Button>
    </div>
  );
}


/** 标题行右侧的「选择」入口。选择模式打开后它让位给操作条,所以进了模式就不再渲染。 */
export function BulkSelectTrigger({ active, onEnter, disabled }: { active: boolean; onEnter: () => void; disabled?: boolean }) {
  const t = useI18n();
  if (active) return null;
  return (
    <Button variant="outline" size="sm" disabled={disabled} onClick={onEnter}>
      <ListChecks size={13} /> {t("bulkSelect")}
    </Button>
  );
}
