import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * shadcn/ui 的 Textarea。和 Input 共用同一套 token 与状态样式:
 * 聚焦环、禁用态、`aria-invalid` 都在组件里,业务代码不再手写字段外观。
 */
function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        // 和 Input 同一套形态(圆角、描边、字号、焦点环),高度交给 rows。
        "flex field-sizing-content min-h-28 w-full rounded-xl border border-input/80 bg-card px-4 py-3 text-[16px] text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.7)] outline-none transition-[border-color,box-shadow,background-color] placeholder:text-muted-foreground focus-visible:border-primary focus-visible:ring-4 focus-visible:ring-primary/15 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-4 aria-invalid:ring-destructive/15 dark:shadow-none",
        className,
      )}
      {...props}
    />
  );
}

export { Textarea };
