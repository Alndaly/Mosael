import * as React from "react"

import { FIELD_SIZE, type FieldSize } from "@/components/ui/control-size"
import { cn } from "@/lib/utils"

export type InputProps = Omit<React.ComponentProps<"input">, "size"> & {
  /**
   * 档位,和 `<Button size>` 同一把尺(见 control-size.ts 的 FIELD_SIZE):
   * `xs` 28 工具栏、`sm` 32 卡片与窄面板、`md` 40 表单(默认)。
   *
   * 挑档看**这一行其它控件多高**。别在 className 里写 `h-*` 改高度 ——
   * `design/fieldScale.test.ts` 会拦下来。原生的 `size`(按字符数定宽)在这里不可用,
   * 宽度用 `w-*` 给。
   */
  size?: FieldSize
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, size = "md", ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          "flex w-full rounded-md border border-field-border bg-field py-1 transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
          FIELD_SIZE[size],
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Input.displayName = "Input"

export { Input }
