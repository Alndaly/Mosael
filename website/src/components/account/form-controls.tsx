"use client";

import {
  AlertCircle,
  ArrowRight,
  Eye,
  EyeOff,
  LoaderCircle,
} from "lucide-react";
import { useState, type InputHTMLAttributes, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

/**
 * 账号表单的零件。
 *
 * 三页共用同一套 label / 错误 / 主按钮,层级才不会被页面各写一遍写歪。输入框的形态
 * (高度、圆角、字号、聚焦环、禁用态、错误环)统一交给 shadcn 的 `Input`,这里只负责
 * 关联 label、把 hint / error 拼进 `aria-describedby`,以及密码可见性这类额外交互。
 * 错误同时走 `aria-invalid` 和 `aria-describedby`,不是只飘一行红字。
 */
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
      <Label htmlFor={id}>{label}</Label>
      <div className="relative">
        <Input
          id={id}
          aria-invalid={Boolean(error)}
          aria-describedby={describedBy}
          className={cn(trailing && "pr-12", className)}
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

/**
 * 6 位数字验证码输入框。仍是 `AccountField`,只是把键盘、自动填充和长度钉死;
 * 发送按钮作为 `trailing` 放在输入框右侧(和密码可见性按钮同一套位置约定)。
 */
export function CodeField({
  id,
  label,
  hint,
  error,
  describedBy,
  trailing,
  ...props
}: Omit<FieldProps, "type" | "trailing"> & { trailing?: ReactNode }) {
  return (
    <AccountField
      {...props}
      id={id}
      label={label}
      hint={hint}
      error={error}
      describedBy={describedBy}
      type="text"
      inputMode="numeric"
      autoComplete="one-time-code"
      pattern="[0-9]{6}"
      maxLength={6}
      placeholder="000000"
      spellCheck={false}
      className="pr-32 font-mono tracking-[0.28em]"
      trailing={trailing}
    />
  );
}

/** 发送验证码 / 重发。冷却时按钮自己禁用并显示剩余秒数,倒计时逻辑仍在表单里。 */
export function SendCodeButton({
  label,
  sendingLabel,
  resendLabel,
  sending,
  cooldown,
  disabled = false,
  onClick,
}: {
  label: string;
  sendingLabel: string;
  resendLabel: string;
  sending: boolean;
  cooldown: number;
  disabled?: boolean;
  onClick: () => void;
}) {
  const blocked = sending || cooldown > 0 || disabled;
  return (
    <button
      type="button"
      aria-busy={sending}
      disabled={blocked}
      onClick={onClick}
      className="absolute inset-y-1 right-1 inline-flex items-center rounded-lg px-3 text-[13px] font-semibold text-primary transition-colors hover:bg-brand-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none"
    >
      {sending && <LoaderCircle className="mr-1.5 size-3.5 animate-spin motion-reduce:animate-none" aria-hidden />}
      {sending ? sendingLabel : cooldown > 0 ? `${resendLabel} (${cooldown}s)` : label}
    </button>
  );
}

/**
 * 登录方式分段控件。
 *
 * 两个按钮是同一页里的两种入口,不是两个页面 —— 切过去时邮箱还在,用户不用重填。
 * 用 `fieldset` + `aria-pressed`:两段就是两个独立开关,Tab 键依次可达,
 * 读屏也能听出当前选中的是哪一个。
 */
export function SegmentedControl<T extends string>({
  id,
  label,
  value,
  options,
  onChange,
  disabled = false,
}: {
  id: string;
  label: string;
  value: T;
  options: ReadonlyArray<{ value: T; label: string }>;
  onChange: (value: T) => void;
  disabled?: boolean;
}) {
  return (
    <fieldset
      id={id}
      aria-label={label}
      className="m-0 grid min-w-0 gap-1 rounded-full border border-border bg-card p-1"
      style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}
    >
      <legend className="sr-only">{label}</legend>
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={selected}
            disabled={disabled}
            onClick={() => onChange(option.value)}
            className={cn(
              "h-11 min-w-0 whitespace-nowrap rounded-full px-2 text-[13px] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring motion-reduce:transition-none sm:px-4 sm:text-[14px]",
              selected
                ? "bg-primary text-primary-foreground shadow-[0_8px_24px_-16px_color-mix(in_oklab,var(--primary)_80%,transparent)]"
                : "text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </fieldset>
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
