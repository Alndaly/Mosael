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
      {/* 动作**对齐整个抬头的竖向中心**,不是对齐标题那一行,也不是对齐整块的底边。
          三种都试过:`items-end` 在说明一长时把按钮拖到最后一行旁边,看着像那句话的一部分;
          `items-start` 则在说明有两三行时把按钮顶在最上面,右边空出一大块。
          `items-center` 两头都不沾 —— 按钮始终落在这一节抬头的视觉重心上。 */}
      <header className="flex items-center justify-between gap-4 px-0.5">
        <div className="min-w-0">
          <h2 className="m-0 text-[17px] font-[650] leading-[1.3] tracking-[-0.015em]">{title}</h2>
          {description && <p className="mb-0 mt-[5px] text-ui-sm leading-[1.55] text-muted-foreground">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
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
        <span className="text-ui-md font-medium">{label}</span>
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
