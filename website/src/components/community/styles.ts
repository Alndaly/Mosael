import { cn } from "@/lib/utils";

/**
 * 社区表单与按钮的类名。**普通模块,不是客户端组件**:服务端组件(分享页的「在 Mosael 中打开」)
 * 和客户端组件都从这里拿同一串 —— 放在 "use client" 模块里的话,服务端拿到的只是一个引用。
 */
export const INPUT =
  "h-11 w-full min-w-0 rounded-xl border border-input bg-card px-3.5 text-sm text-foreground placeholder:text-muted-foreground focus-visible:border-primary focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-primary/20 disabled:opacity-60 aria-invalid:border-destructive";

export const TEXTAREA =
  "min-h-24 w-full min-w-0 rounded-xl border border-input bg-card px-3.5 py-2.5 text-sm leading-6 text-foreground placeholder:text-muted-foreground focus-visible:border-primary focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-primary/20";

const BUTTON_BASE =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-full px-5 text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-55";

export const BUTTON = {
  primary: cn(BUTTON_BASE, "bg-primary text-primary-foreground hover:bg-primary/88"),
  secondary: cn(BUTTON_BASE, "border border-border bg-card hover:border-foreground/30"),
  danger: cn(BUTTON_BASE, "border border-destructive/40 bg-card text-destructive hover:bg-destructive/10"),
  ghost: cn(BUTTON_BASE, "min-h-9 px-3 text-muted-foreground hover:bg-secondary hover:text-foreground"),
} as const;
