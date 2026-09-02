import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * 对话流里的**行内标记**:状态、系统提示、带边框的一行、带标签的分隔线。
 *
 * 取自 shadcn/ui 的 marker(https://ui.shadcn.com/docs/components/base/marker),按本项目约定
 * 改了两处:`Slot` 用我们已有的 `@radix-ui/react-slot`(项目其余组件都用它,不再引第二个包),
 * 字号用项目的流体刻度 `text-ui-xs` 而不是固定的 `text-sm` —— 14px 在这套 12.5px 正文的版面里
 * 是偏大的,而"标记"本就该比正文轻。
 */
const markerVariants = cva(
  "group/marker relative flex min-h-4 w-full items-center gap-2 text-left text-ui-xs text-muted-foreground [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "",
        separator:
          "before:mr-1 before:h-px before:min-w-0 before:flex-1 before:bg-border after:ml-1 after:h-px after:min-w-0 after:flex-1 after:bg-border",
        border: "border-b border-border pb-2",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

function Marker({
  className,
  variant = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"div"> &
  VariantProps<typeof markerVariants> & {
    asChild?: boolean;
  }) {
  const Comp = asChild ? Slot : "div";
  return (
    <Comp
      data-slot="marker"
      data-variant={variant}
      className={cn(markerVariants({ variant, className }))}
      {...props}
    />
  );
}

function MarkerIcon({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      data-slot="marker-icon"
      aria-hidden="true"
      className={cn(
        "inline-flex size-4 shrink-0 items-center justify-center [&_svg:not([class*='size-'])]:size-4",
        className,
      )}
      {...props}
    />
  );
}

/**
 * 内容槽。**字号写在这里,而不是只写在根上** —— 根用 asChild 渲染成 `<button>` 时,
 * design/tokens.css 里那条无层级的 `button{font:inherit}` 会压过 utilities,根上的
 * `text-ui-xs` 静默失效(class 还在,尺寸回落到继承值)。span 不在那条重置的选择器里,
 * 挂在这儿才一定落得下去。根上那份保留:变体渲染成 div 时由它生效。
 */
function MarkerContent({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      data-slot="marker-content"
      className={cn(
        "min-w-0 text-ui-xs [overflow-wrap:break-word] group-data-[variant=separator]/marker:flex-none group-data-[variant=separator]/marker:text-center",
        className,
      )}
      {...props}
    />
  );
}

export { Marker, MarkerIcon, MarkerContent, markerVariants };
