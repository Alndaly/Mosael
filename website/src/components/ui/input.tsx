import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * shadcn/ui 的 Input。
 *
 * 形态归组件:高度、圆角、字号、边框、聚焦环、禁用态和 `aria-invalid` 都写在这里,
 * 业务代码只传值和事件,不再各自拼一套字段样式。颜色全部走主题 token,明暗两档同一份。
 * 16px 字号在移动端也保留(iOS 聚焦时不会把页面放大),桌面端再收到 14px。
 */
function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        // 站点的形态:这站的字段本来是 h-12 / rounded-xl / 16px(shadcn 默认 h-8 会整站变小一号)。
        // 形态归组件——业务代码不许再覆盖高度、圆角、字号。
        "h-12 w-full min-w-0 rounded-xl border border-input/80 bg-card px-4 text-[16px] text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.7)] outline-none transition-[border-color,box-shadow,background-color] placeholder:text-muted-foreground focus-visible:border-primary focus-visible:ring-4 focus-visible:ring-primary/15 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-4 aria-invalid:ring-destructive/15 file:border-0 file:bg-transparent file:text-[15px] file:font-medium dark:shadow-none",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
