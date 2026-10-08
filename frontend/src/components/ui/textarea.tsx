import * as React from "react"

import { FIELD_INVALID, FIELD_TEXTAREA } from "@/components/ui/control-size"
import { cn } from "@/lib/utils"

const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.ComponentProps<"textarea">
>(({ className, ...props }, ref) => {
  return (
    <textarea
      className={cn(
        //: 和 md 字段同一种外观、同一套留白和字号(control-size 的 FIELD_TEXTAREA),高度随内容。
        "flex w-full rounded-md border border-field-border bg-field placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
        FIELD_TEXTAREA,
        FIELD_INVALID,
        className
      )}
      ref={ref}
      {...props}
    />
  )
})
Textarea.displayName = "Textarea"

export { Textarea }
