import * as React from "react";
import { ChevronRight } from "lucide-react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

/**
 * 「高级」这一类折叠开关:**一行字,不是按钮** —— 灰的标签、一个会转的箭头,后面可以跟几项(`count`)或者一句提示(`hint`,
 * `wide` 时摆在右头)。任何状态下都没有底色、边框、胶囊形状,悬停只变字的颜色;只有键盘聚焦时才有焦点环。它和旁边的设置行
 * 左对齐(没有内边距,不像按钮那样缩进)。
 *
 * 此前应用里有三种写法:插件工具表单里的一行字、模型设置里的整行、本机服务卡片里的一颗 ghost 按钮 —— 最后那个在维护者的界面里
 * 是一颗实心胶囊,读起来像要点的动作。开合走 Collapsible 的动画;`aria-expanded` / `aria-controls` 由它给。内容收起时不挂载。
 */
export function Disclosure({
  label,
  open,
  onOpenChange,
  count,
  hint,
  wide = false,
  className,
  triggerClassName,
  contentClassName,
  children,
}: {
  label: React.ReactNode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 收着几项(跟在标签后面)。 */
  count?: number;
  /** 一句提示;`wide` 时和箭头一起摆在右头,否则跟在标签后面。 */
  hint?: React.ReactNode;
  /** 占满一整行:标签在左,提示和箭头在右。 */
  wide?: boolean;
  className?: string;
  /** 开关那一行外面的间距(放在分隔线隔开的设置组里时用)。 */
  triggerClassName?: string;
  contentClassName?: string;
  children: React.ReactNode;
}) {
  const chevron = (
    <ChevronRight size={13} aria-hidden className="shrink-0 transition-transform duration-100 group-data-[state=open]:rotate-90 motion-reduce:transition-none" />
  );
  return (
    <Collapsible open={open} onOpenChange={onOpenChange} className={className}>
      <div className={triggerClassName}>
        <CollapsibleTrigger asChild>
          <button
            type="button"
            data-disclosure-trigger
            className={cn(
              "group inline-flex cursor-pointer items-center gap-1 rounded-sm border-0 bg-transparent p-0 text-left text-ui-sm font-medium",
              "text-muted-foreground transition-colors hover:text-foreground",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              wide ? "flex w-full justify-between gap-2" : "w-fit",
            )}
          >
            {wide ? (
              <>
                <span>{label}</span>
                <span className="flex items-center gap-1 text-ui-xs font-normal">
                  {hint}
                  {count !== undefined && <span className="tabular-nums">{count}</span>}
                  {chevron}
                </span>
              </>
            ) : (
              <>
                {chevron}
                <span>{label}</span>
                {count !== undefined && <span className="text-ui-xs font-normal tabular-nums">{count}</span>}
                {hint && <span className="text-ui-xs font-normal">{hint}</span>}
              </>
            )}
          </button>
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent className={contentClassName}>{children}</CollapsibleContent>
    </Collapsible>
  );
}
