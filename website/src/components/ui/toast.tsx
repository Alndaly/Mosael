import * as React from "react";
import { X } from "lucide-react";
import { Toast as ToastPrimitive } from "radix-ui";

import { cn } from "@/lib/utils";

/**
 * shadcn/ui 的 toast,底部原子是 `radix-ui` 里现成的 Toast —— 没有为它新增依赖。
 *
 * 为什么是 toast 而不是提示条:「验证码已发送」「已保存」「第三方登录回来了」都是**做成了**,
 * 说完就该消失。提示条会一直占着版面,把下面的字段整体往下推,而用户此刻要看的正是字段。
 * 错误不走这里 —— 它得留在出错的字段旁边(见 `form-controls.tsx` 的 `FormAlert`)。
 *
 * 可访问性由 Radix 负责:每条 toast 自带 `role="status"` 与 `aria-live`,viewport 是一个带
 * `aria-label` 的 region(F8 可跳进来)。**这里不再包第二层 `aria-live`**:那会让读屏把同一句话
 * 播报两遍。toast 也不接管焦点;想手动关就走 `ToastClose`(aria-label 由调用方按当前语言给)。
 */
function ToastProvider({ ...props }: React.ComponentProps<typeof ToastPrimitive.Provider>) {
  return <ToastPrimitive.Provider {...props} />;
}

function ToastViewport({ className, ...props }: React.ComponentProps<typeof ToastPrimitive.Viewport>) {
  return (
    <ToastPrimitive.Viewport
      data-slot="toast-viewport"
      className={cn(
        "fixed top-0 z-100 flex max-h-svh w-full flex-col-reverse gap-2 p-4 outline-none sm:top-auto sm:right-0 sm:bottom-0 sm:flex-col sm:p-6 md:max-w-[26rem]",
        className,
      )}
      {...props}
    />
  );
}

function Toast({ className, ...props }: React.ComponentProps<typeof ToastPrimitive.Root>) {
  return (
    <ToastPrimitive.Root
      data-slot="toast"
      className={cn(
        "group pointer-events-auto relative flex w-full items-start gap-3 overflow-hidden rounded-lg border border-border bg-card p-4 pr-11 text-foreground shadow-lg",
        "transition-all data-[swipe=cancel]:translate-x-0 data-[swipe=end]:translate-x-(--radix-toast-swipe-end-x) data-[swipe=move]:translate-x-(--radix-toast-swipe-move-x) data-[swipe=move]:transition-none",
        "data-[state=open]:animate-in data-[state=open]:slide-in-from-right-full data-[state=closed]:animate-out data-[state=closed]:fade-out-80 data-[state=closed]:slide-out-to-right-full",
        "motion-reduce:animate-none motion-reduce:transition-none",
        className,
      )}
      {...props}
    />
  );
}

function ToastTitle({ className, ...props }: React.ComponentProps<typeof ToastPrimitive.Title>) {
  return (
    <ToastPrimitive.Title
      data-slot="toast-title"
      className={cn("m-0 text-sm font-semibold leading-6", className)}
      {...props}
    />
  );
}

function ToastDescription({ className, ...props }: React.ComponentProps<typeof ToastPrimitive.Description>) {
  return (
    <ToastPrimitive.Description
      data-slot="toast-description"
      className={cn("m-0 text-[13px] leading-6 text-muted-foreground", className)}
      {...props}
    />
  );
}

function ToastClose({ className, children, ...props }: React.ComponentProps<typeof ToastPrimitive.Close>) {
  return (
    <ToastPrimitive.Close
      data-slot="toast-close"
      className={cn(
        "absolute top-2.5 right-2.5 inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring motion-reduce:transition-none",
        className,
      )}
      {...props}
    >
      {children ?? <X className="size-3.5" aria-hidden />}
    </ToastPrimitive.Close>
  );
}

export { Toast, ToastClose, ToastDescription, ToastProvider, ToastTitle, ToastViewport };
