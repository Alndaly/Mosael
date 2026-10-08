import * as React from "react"

import { CHIP_SIZE } from "@/components/ui/control-size"
import { cn } from "@/lib/utils"

/**
 * 胶囊筛选:一排会折行的筛选条件(「全部 · 图像 · 视频」、标签),可以单选也可以多选。高 28(和 xs 对齐),全圆,12px 字。
 * 和分段控件的分界:会折行、可多选、是「筛」不是「切换视图」→ 胶囊。规格见 docs/DESIGN_LANGUAGE.md「选择类控件」。
 *
 * 选中的语义跟着这一排是什么:默认是切换按钮(`aria-pressed`);一排互斥、要当页签读的给 `role="tab"`(念 aria-selected),
 * 当单选读的给 `role="radio"`(念 aria-checked)—— 外面那一层(tablist / radiogroup / group)和键盘由调用方给。
 */
export function chipClass(selected: boolean): string {
  return cn(
    "inline-flex shrink-0 cursor-pointer items-center gap-1 whitespace-nowrap border font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50",
    CHIP_SIZE,
    selected
      ? "border-[color-mix(in_srgb,var(--primary)_40%,transparent)] bg-accent text-accent-foreground"
      : "border-border bg-transparent text-muted-foreground hover:bg-secondary hover:text-foreground",
  )
}

export type ChipProps = Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "className"> & {
  selected: boolean
  /** 名字前面的图标,12px。 */
  icon?: React.ReactNode
  /** 只给排版用(外边距、对齐);高度、留白、圆角、字号由这一档定。 */
  className?: string
}

export const Chip = React.forwardRef<HTMLButtonElement, ChipProps>(
  ({ selected, icon, className, role, type = "button", children, ...props }, ref) => {
    const state =
      role === "tab" ? { "aria-selected": selected } : role === "radio" ? { "aria-checked": selected } : { "aria-pressed": selected }
    return (
      <button ref={ref} type={type} role={role} data-chip="" className={cn(chipClass(selected), className)} {...state} {...props}>
        {icon}
        {children}
      </button>
    )
  },
)
Chip.displayName = "Chip"
