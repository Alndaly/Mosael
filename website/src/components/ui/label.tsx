"use client";

import * as React from "react";
import { Label as LabelPrimitive } from "radix-ui";

import { cn } from "@/lib/utils";

/**
 * shadcn/ui 的 Label(底层是现成的 `radix-ui` Label,没有新增依赖)。
 *
 * 业务代码用 `htmlFor` + 控件 `id` 显式关联,而不是把控件包进 label:后者在自定义
 * 组合控件里容易把点击劫走。读屏点和点标签都能落到同一个控件上。
 */
function Label({ className, ...props }: React.ComponentProps<typeof LabelPrimitive.Root>) {
  return (
    <LabelPrimitive.Root
      data-slot="label"
      className={cn(
        "flex items-center gap-2 text-sm leading-none font-medium select-none group-data-[disabled=true]:pointer-events-none group-data-[disabled=true]:opacity-50 peer-disabled:cursor-not-allowed peer-disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

export { Label };
