import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * 单选:选项多、需要说明文字、或者放在表单里要「确定」才生效的互斥选择。两到五个短选项、切换立刻生效的用分段控件
 * (segmented),超过五个或很长的用下拉。规格见 docs/DESIGN_LANGUAGE.md「选择类控件」。
 *
 * 一项 = 16px 的圆 + 名字(14px)+ 可选的一行说明(12px 次要色);选中强调色描边加圆点。
 * 底下是原生的 `<input type="radio">`(同名一组):方向键在组里换、Tab 只停在选中的那一个、表单提交、读屏念「单选按钮 · 已选中
 * 第 2 个,共 3 个」都是浏览器给的,不用自己写。此前二十来处 `role="radiogroup"` 各画各的。
 */
export type RadioOption<T extends string> = {
  value: T
  label: React.ReactNode
  description?: React.ReactNode
  disabled?: boolean
}

export function RadioGroup<T extends string>({
  value,
  onValueChange,
  options,
  name,
  orientation = "vertical",
  indicator = "inline",
  disabled = false,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
  className,
}: {
  value: T | null
  onValueChange: (value: T) => void
  options: RadioOption<T>[]
  /** 同一组的名字(表单提交时用);不给就生成一个。 */
  name?: string
  orientation?: "vertical" | "horizontal"
  /**
   * 圆放在哪。`inline`:名字左边(默认)。`corner`:叠在选项内容的左上角里 —— 选项本身是一张图(参考图的几个视角)时用,
   * 圆在图外会多占一列、和图隔着一道缝,看着像两件东西。
   */
  indicator?: "inline" | "corner"
  disabled?: boolean
  "aria-label"?: string
  "aria-labelledby"?: string
  /** 只给排版用(外边距、宽度)。 */
  className?: string
}) {
  const generated = React.useId()
  const group = name ?? generated
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      aria-labelledby={ariaLabelledBy}
      aria-orientation={orientation}
      className={cn(orientation === "vertical" ? "grid gap-2.5" : "flex flex-wrap items-start gap-x-5 gap-y-2.5", className)}
    >
      {options.map((option) => {
        const off = disabled || option.disabled
        return (
          <label
            key={option.value}
            data-radio-option={option.value}
            className={cn(
              indicator === "corner" ? "relative block min-w-0" : "flex min-w-0 items-start gap-2.5",
              off ? "cursor-not-allowed opacity-50" : "cursor-pointer",
            )}
          >
            <span
              className={cn(
                "grid size-4 shrink-0 place-items-center",
                indicator === "corner" ? "absolute left-2 top-2 z-10" : "relative mt-0.5",
              )}
            >
              <input
                type="radio"
                name={group}
                value={option.value}
                checked={value === option.value}
                disabled={off}
                onChange={() => onValueChange(option.value)}
                className="peer absolute inset-0 m-0 cursor-[inherit] appearance-none rounded-full border border-input bg-field transition-colors checked:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background"
              />
              {/* relative:圆点得画在 input(绝对定位、有底色)上面 —— 不定位的话它排在 input 底下,被那层底色盖住。 */}
              <span aria-hidden className="pointer-events-none relative size-2 rounded-full bg-action opacity-0 transition-opacity peer-checked:opacity-100" />
            </span>
            <span className="grid min-w-0 gap-0.5">
              <span className="text-ui-sm leading-5">{option.label}</span>
              {option.description && <span className="text-ui-xs leading-4 text-muted-foreground">{option.description}</span>}
            </span>
          </label>
        )
      })}
    </div>
  )
}
