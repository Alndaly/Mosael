import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * shadcn/ui 的 Input。
 *
 * 形态归组件:高度、圆角、字号、边框、聚焦环、禁用态和 `aria-invalid` 都写在这里,
 * 业务代码只传值和事件,不再各自拼一套字段样式。颜色全部走主题 token,明暗两档同一份。
 * 16px 字号在移动端也保留(iOS 聚焦时不会把页面放大),桌面端再收到 14px。
 */
function Input({
  className,
  type,
  density = "comfortable",
  ...props
}: React.ComponentProps<"input"> & {
  /**
   * 营销页用 `comfortable`；管理台用 `compact`（shadcn 标准密度）。
   * 两档都只在这里定义，业务代码不许再各自覆盖 h-9 / rounded-md / text-sm。
   */
  density?: "comfortable" | "compact";
}) {
  return (
    <input
      type={type}
      data-slot="input"
      data-density={density}
      className={cn(
        density === "compact"
          ? "h-9 w-full min-w-0 rounded-md border border-input bg-transparent px-3 py-1 text-sm text-foreground shadow-xs outline-none transition-[color,box-shadow] placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:bg-input/30 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40"
          : "h-12 w-full min-w-0 rounded-xl border border-input/80 bg-card px-4 text-[16px] text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.7)] outline-none transition-[border-color,box-shadow,background-color] placeholder:text-muted-foreground focus-visible:border-primary focus-visible:ring-4 focus-visible:ring-primary/15 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-4 aria-invalid:ring-destructive/15 file:border-0 file:bg-transparent file:text-[15px] file:font-medium dark:shadow-none",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
