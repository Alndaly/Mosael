"use client";

/**
 * 社区里表单与小部件的共用外形:输入框、按钮、提示条、弹窗、分段按钮。
 *
 * 和站里其它地方同一套语汇(圆角 xl 的输入框、全圆角的按钮、primary 只给主操作),
 * 不另起一套 —— 登录页、提交页、审核页放在一起看要像同一个网站。
 */
import { Dialog as DialogPrimitive } from "radix-ui";
import { AlertCircle, CheckCircle2, Loader2, X } from "lucide-react";
import * as React from "react";

import { BUTTON, INPUT, TEXTAREA } from "@/components/community/styles";
import { cn } from "@/lib/utils";

// 类名常量在一个普通模块里(styles.ts):服务端组件也要用,而从 "use client" 模块 import 的
// 非组件值在服务端只是一个引用,不是字符串。客户端组件照旧从这里拿。
export { BUTTON, INPUT, TEXTAREA };

export function Field({
  label,
  hint,
  error,
  htmlFor,
  children,
  aside,
}: {
  label: string;
  hint?: React.ReactNode;
  error?: string | null;
  htmlFor?: string;
  children: React.ReactNode;
  aside?: React.ReactNode;
}) {
  return (
    <div className="grid gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={htmlFor} className="text-sm font-medium">
          {label}
        </label>
        {aside}
      </div>
      {children}
      {error ? (
        <p className="m-0 text-xs text-destructive" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="m-0 text-xs leading-5 text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  );
}

export function Notice({ tone, children }: { tone: "error" | "success" | "info"; children: React.ReactNode }) {
  const Icon = tone === "success" ? CheckCircle2 : AlertCircle;
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn(
        "flex items-start gap-2.5 rounded-xl border px-3.5 py-3 text-sm leading-6",
        tone === "error" && "border-destructive/30 bg-destructive/8 text-destructive",
        tone === "success" && "border-primary/30 bg-brand-soft text-foreground",
        tone === "info" && "border-border bg-secondary/60 text-muted-foreground",
      )}
    >
      <Icon className={cn("mt-1 size-4 shrink-0", tone === "success" && "text-primary")} aria-hidden />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("size-4 animate-spin motion-reduce:animate-none", className)} aria-hidden />;
}

export function SubmitButton({
  pending,
  children,
  pendingLabel,
  className,
  variant = "primary",
  ...props
}: React.ComponentProps<"button"> & { pending?: boolean; pendingLabel?: string; variant?: keyof typeof BUTTON }) {
  return (
    <button type="submit" disabled={pending || props.disabled} className={cn(BUTTON[variant], className)} {...props}>
      {pending && <Spinner />}
      {pending && pendingLabel ? pendingLabel : children}
    </button>
  );
}

/** 两三个选项的分段切换(登录方式、可见性、时间范围)。 */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: readonly { id: T; label: string }[];
  onChange: (next: T) => void;
  label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="grid auto-cols-fr grid-flow-col rounded-full border border-border bg-secondary/60 p-1">
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          role="tab"
          aria-selected={value === option.id}
          onClick={() => onChange(option.id)}
          className={cn(
            "min-h-9 rounded-full px-3 text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
            value === option.id ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** 居中的弹窗(举报、确认、看大图)。Esc、点遮罩关闭,焦点锁在里面。 */
export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  closeLabel,
  wide = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  closeLabel: string;
  wide?: boolean;
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-[60] bg-ink/45 backdrop-blur-sm data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content
          className={cn(
            "fixed top-1/2 left-1/2 z-[61] grid max-h-[calc(100dvh-2rem)] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 gap-4 overflow-y-auto rounded-2xl border border-border bg-popover p-5 text-popover-foreground shadow-2xl sm:p-6",
            wide ? "max-w-5xl" : "max-w-md",
          )}
        >
          <div className="flex items-start justify-between gap-4">
            <div className="grid gap-1">
              <DialogPrimitive.Title className="m-0 text-base font-semibold">{title}</DialogPrimitive.Title>
              {description ? (
                <DialogPrimitive.Description className="m-0 text-sm text-muted-foreground">{description}</DialogPrimitive.Description>
              ) : (
                <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
              )}
            </div>
            <DialogPrimitive.Close
              aria-label={closeLabel}
              className="-m-1.5 grid size-9 shrink-0 place-items-center rounded-full text-muted-foreground hover:bg-secondary hover:text-foreground"
            >
              <X className="size-4" aria-hidden />
            </DialogPrimitive.Close>
          </div>
          {children}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/** 一整块的空态 / 错误态。 */
export function StatePanel({ icon, title, body, children }: { icon?: React.ReactNode; title: string; body?: string; children?: React.ReactNode }) {
  return (
    <div className="grid place-items-center gap-3 rounded-2xl border border-dashed border-border px-6 py-16 text-center">
      {icon}
      <p className="m-0 font-semibold">{title}</p>
      {body && <p className="m-0 max-w-md text-sm leading-6 text-muted-foreground">{body}</p>}
      {children}
    </div>
  );
}

/** 把一个错误变成给人看的一句话:服务给了译好的 message 就用它。 */
export function errorText(error: unknown, fallback: string, network: string): string {
  if (error && typeof error === "object" && "code" in error) {
    const { code, message } = error as { code: string; message: string };
    if (code === "network") return network;
    if (message && message !== code) return message;
  }
  return fallback;
}

/** 复制到剪贴板,1.5 秒内显示「已复制」。 */
export function useCopy(): [boolean, (text: string) => void] {
  const [copied, setCopied] = React.useState(false);
  React.useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copied]);
  const copy = React.useCallback((text: string) => {
    void navigator.clipboard?.writeText(text).then(() => setCopied(true));
  }, []);
  return [copied, copy];
}
