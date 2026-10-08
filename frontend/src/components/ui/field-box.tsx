import * as React from "react"

import type { FieldSize } from "@/components/ui/control-size"
import { fieldTriggerClass } from "@/components/ui/field-trigger"
import { cn } from "@/lib/utils"

/**
 * 「长得是一个字段,但不是下拉、也不是输入框」的那一格:只读的值(插件配置里只有一个可选值的那一项,右头一把锁)、
 * 一条取色(色块 + 色值 + 清除)。和旁边的输入框、下拉同一种描边、底色、档位,排成一列时逐像素对齐 ——
 * 一行光秃秃的文字夹在两格字段中间,读起来像「这块没做完」。
 *
 * 不画下拉箭头(它点不开);右头放什么由调用方给(锁、清除)。`as="label"` 时整条都能点到里面的控件(取色器)。
 * 此前这几处直接借 fieldTriggerClass 自己拼 —— 那是下拉触发器的样子,借来画别的东西,改下拉时它们跟着变形
 * (棘轮 design/nativeButtons.test.ts 只许基础组件用它)。
 */
export function FieldBox({
  as: Tag = "div",
  size = "md",
  className,
  children,
  ...props
}: {
  as?: "div" | "label"
  size?: FieldSize
  /** 只给排版用(宽度、指针、对齐、子项间距)。 */
  className?: string
  children: React.ReactNode
} & Omit<React.HTMLAttributes<HTMLElement>, "className" | "children">) {
  return (
    <Tag data-field-box="" className={cn(fieldTriggerClass(size), "text-foreground", className)} {...props}>
      {children}
    </Tag>
  )
}
