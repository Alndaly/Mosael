import React from "react";

import { cn } from "@/lib/utils";

/**
 * Shared settings building blocks: every section is a Group (title +
 * description + optional header actions) containing Rows (label +
 * description on the left, control on the right). Keeps all five sections
 * on one consistent grid instead of ad-hoc card layouts.
 *
 * Row dividers come from the group body's `[&>*+*]:border-t`, so a Group's children must be
 * only Rows and Blocks. Any other element between two of them — including a display:none
 * one, which sibling selectors do not skip — adds or shifts a divider.
 * Hidden file inputs belong inside the Row whose control opens them.
 */

export function SettingsGroup({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  /** 没有内容时**不画那个框** —— 只有标题和说明的分组(比如"自助注册已开放")本来就没有行,
   *  空着渲染出来是一条无缘无故的横线。 */
  children?: React.ReactNode;
}) {
  return (
    <section className="grid gap-2 [[data-appearance=glass]_&]:[-webkit-backdrop-filter:blur(var(--app-blur,16px))_saturate(1.35)] [[data-appearance=glass]_&]:[backdrop-filter:blur(var(--app-blur,16px))_saturate(1.35)]">
      {/* 动作**对齐标题那一行**,不对齐整块的底边。`items-end` 在说明只有一行时看不出区别,
          说明一长就把按钮拖到最后一行旁边 —— 它看起来像是那句话的一部分,而不是这一节的动作
          (自动放行准则那一屏的说明有三行,按钮正卡在换行处)。 */}
      <header className="flex items-start justify-between gap-4 px-0.5">
        <div className="min-w-0">
          <h2 className="m-0 text-[17px] font-[650] leading-[1.3] tracking-[-0.015em]">{title}</h2>
          {description && <p className="mb-0 mt-[5px] text-[12.5px] leading-[1.55] text-muted-foreground">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2 pt-0.5">{actions}</div>}
      </header>
      {React.Children.toArray(children).some(Boolean) && (
        <div className="grid overflow-hidden rounded-lg border border-border bg-panel shadow-[var(--shadow-panel)] [&>*+*]:border-t [&>*+*]:border-border">
          {children}
        </div>
      )}
    </section>
  );
}

export function SettingsRow({
  id,
  className,
  controlClassName,
  label,
  description,
  children,
}: {
  id?: string;
  className?: string;
  controlClassName?: string;
  label: string;
  description?: string;
  children?: React.ReactNode;
}) {
  return (
    <div id={id} className={cn("grid grid-cols-[minmax(0,1fr)_auto] items-center gap-5 px-3.5 py-3", className)}>
      <div className="grid min-w-0 gap-0.5">
        <span className="text-[13px] font-medium">{label}</span>
        {description && <small className="text-xs leading-[1.45] text-muted-foreground">{description}</small>}
      </div>
      {children && <div className={cn("flex shrink-0 items-center gap-1.5", controlClassName)}>{children}</div>}
    </div>
  );
}

/** Full-width slot inside a group (forms, QR panels, lists). */
export function SettingsBlock({ children }: { children: React.ReactNode }) {
  return <div className="grid gap-2 px-3.5 py-2.5">{children}</div>;
}
