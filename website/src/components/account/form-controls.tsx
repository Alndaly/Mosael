"use client";

import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  Eye,
  EyeOff,
  LoaderCircle,
} from "lucide-react";
import { useState, type InputHTMLAttributes, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * 账号表单的零件。
 *
 * 三页共用同一套 label / 错误 / 主按钮,层级才不会被页面各写一遍写歪。输入框固定
 * 48px 高、16px 字号(iOS 不会在聚焦时缩放),聚焦环和错误环都留给键盘与读屏:
 * 错误同时走 `aria-invalid` 和 `aria-describedby`,不是只飘一行红字。
 */
const FIELD =
  "h-12 w-full rounded-xl border border-input/80 bg-card px-4 text-[16px] text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.7)] outline-none transition-[border-color,box-shadow,background-color] placeholder:text-muted-foreground focus-visible:border-primary focus-visible:ring-4 focus-visible:ring-primary/15 aria-invalid:border-destructive aria-invalid:ring-4 aria-invalid:ring-destructive/15 dark:shadow-none";

type FieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "id"> & {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  /** 外部错误 / 说明区域的 id,和字段自己的 hint、error 一起进 aria-describedby。 */
  describedBy?: string;
  trailing?: ReactNode;
};

export function AccountField({
  id,
  label,
  hint,
  error,
  describedBy: externalDescription,
  trailing,
  className,
  ...props
}: FieldProps) {
  const hintId = hint ? `${id}-hint` : "";
  const errorId = error ? `${id}-error` : "";
  const describedBy = [hintId, errorId, externalDescription].filter(Boolean).join(" ") || undefined;

  return (
    <div className="grid min-w-0 gap-2">
      <label htmlFor={id} className="text-[13px] font-medium leading-5 text-foreground">
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          aria-invalid={Boolean(error)}
          aria-describedby={describedBy}
          className={cn(FIELD, trailing && "pr-12", className)}
          {...props}
        />
        {trailing}
      </div>
      {hint && (
        <p id={hintId} className="text-xs leading-5 text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} role="alert" className="flex items-start gap-1.5 text-[13px] leading-5 text-destructive">
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
          {error}
        </p>
      )}
    </div>
  );
}

export function PasswordField({
  id,
  label,
  hint,
  error,
  showPassword,
  hidePassword,
  describedBy,
  ...props
}: Omit<FieldProps, "trailing" | "type"> & {
  showPassword: string;
  hidePassword: string;
}) {
  const [visible, setVisible] = useState(false);

  return (
    <AccountField
      {...props}
      id={id}
      label={label}
      hint={hint}
      error={error}
      describedBy={describedBy}
      type={visible ? "text" : "password"}
      trailing={
        <button
          type="button"
          aria-label={visible ? hidePassword : showPassword}
          aria-pressed={visible}
          title={visible ? hidePassword : showPassword}
          onClick={() => setVisible((current) => !current)}
          className="absolute inset-y-0 right-0 inline-flex w-12 items-center justify-center rounded-r-xl text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring"
        >
          {visible ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
        </button>
      }
    />
  );
}

export function FormAlert({
  id,
  title,
  children,
}: {
  id?: string;
  title?: string;
  children: ReactNode;
}) {
  return (
    <div
      id={id}
      role="alert"
      className="flex items-start gap-3 rounded-2xl border border-destructive/25 bg-destructive/5 px-4 py-3.5 text-destructive"
    >
      <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 text-[13px] leading-6">
        {title && <p className="m-0 font-semibold">{title}</p>}
        <p className="m-0">{children}</p>
      </div>
    </div>
  );
}

export function FormNotice({ children }: { children: ReactNode }) {
  return (
    <output
      aria-live="polite"
      className="flex items-start gap-3 rounded-2xl border border-primary/20 bg-brand-soft px-4 py-3.5 text-accent"
    >
      <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span className="m-0 min-w-0 text-[13px] leading-6">{children}</span>
    </output>
  );
}

export function SubmitButton({
  label,
  busyLabel,
  busy,
}: {
  label: string;
  busyLabel: string;
  busy: boolean;
}) {
  return (
    <Button
      type="submit"
      aria-busy={busy}
      disabled={busy}
      className="group h-13 w-full rounded-full bg-primary px-6 text-[15px] font-semibold text-primary-foreground shadow-[0_10px_30px_-16px_color-mix(in_oklab,var(--primary)_75%,transparent)] transition-[background-color,transform,box-shadow] hover:bg-accent hover:shadow-[0_14px_34px_-16px_color-mix(in_oklab,var(--primary)_85%,transparent)] focus-visible:ring-4 focus-visible:ring-primary/25 active:translate-y-px disabled:opacity-60 motion-reduce:transition-none"
    >
      <span className="inline-flex items-center justify-center gap-2">
        {busy ? (
          <>
            <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
            {busyLabel}
          </>
        ) : (
          <>
            {label}
            <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5 motion-reduce:transition-none" aria-hidden />
          </>
        )}
      </span>
    </Button>
  );
}
