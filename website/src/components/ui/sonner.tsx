"use client";

import { useTheme } from "next-themes";
import { Toaster as Sonner, type ToasterProps } from "sonner";

/**
 * shadcn/ui 现在推荐的 toast 出口:Sonner。
 *
 * 旧的 Radix Toast 在 shadcn 文档里已标 deprecated;这里只包一层把站点主题、读屏区域名
 * 和关闭按钮文案接进来,其余队列、进场退场、滑动关闭都交给 Sonner。
 */
function Toaster({ label, closeLabel, ...props }: ToasterProps & { label?: string; closeLabel?: string }) {
  const { theme = "system" } = useTheme();
  return (
    <Sonner
      theme={theme as ToasterProps["theme"]}
      className="toaster group"
      richColors
      closeButton
      containerAriaLabel={label}
      toastOptions={{
        closeButtonAriaLabel: closeLabel,
        classNames: {
          toast: "group toast group-[.toaster]:border-border group-[.toaster]:bg-card group-[.toaster]:text-foreground group-[.toaster]:shadow-lg",
          description: "group-[.toast]:text-muted-foreground",
          actionButton: "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
          cancelButton: "group-[.toast]:bg-muted group-[.toast]:text-muted-foreground",
        },
      }}
      {...props}
    />
  );
}

export { Toaster };
