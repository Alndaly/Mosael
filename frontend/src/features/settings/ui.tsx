import React from "react";

import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

/**
 * Shared settings building blocks: every section is a Group (title +
 * description + optional header actions) containing Rows (label +
 * description on the left, control on the right). Groups are deliberately
 * flat: the settings page already owns the surrounding panel, so another
 * rounded card here would create a frame inside a frame.
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
  className,
  contentClassName,
  children,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  className?: string;
  contentClassName?: string;
  /** 没有内容时**不画那个框** —— 只有标题和说明的分组(比如"自助注册已开放")本来就没有行,
   *  空着渲染出来是一条无缘无故的横线。 */
  children?: React.ReactNode;
}) {
  const hasContent = React.Children.toArray(children).some(Boolean);
  return (
    <section data-slot="settings-group" className={cn("grid gap-0", className)}>
      {/* 动作**对齐整个抬头的竖向中心**,不是对齐标题那一行,也不是对齐整块的底边。
          三种都试过:`items-end` 在说明一长时把按钮拖到最后一行旁边,看着像那句话的一部分;
          `items-start` 则在说明有两三行时把按钮顶在最上面,右边空出一大块。
          `items-center` 两头都不沾 —— 按钮始终落在这一节抬头的视觉重心上。 */}
      <header
        data-slot="settings-group-header"
        className={cn(
          "flex items-center justify-between gap-4 px-0.5",
          hasContent && "border-b border-border/70 pb-3",
        )}
      >
        <div className="min-w-0">
          <h2
            data-slot="settings-group-title"
            className="m-0 text-[18px] font-[650] leading-[1.25] tracking-[-0.018em]"
          >
            {title}
          </h2>
          {description && (
            <p
              data-slot="settings-group-description"
              className="mb-0 mt-1.5 max-w-[72rem] text-[13.5px] leading-[1.55] text-muted-foreground"
            >
              {description}
            </p>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </header>
      {hasContent && (
        <div
          data-slot="settings-group-content"
          className={cn("grid [&>*+*]:border-t [&>*+*]:border-border/70", contentClassName)}
        >
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
    <div id={id} className={cn("grid grid-cols-[minmax(0,1fr)_auto] items-center gap-5 px-0.5 py-3.5", className)}>
      <div className="grid min-w-0 gap-1">
        <span data-slot="settings-row-label" className="text-[15px] font-semibold leading-[1.35]">{label}</span>
        {description && (
          <small data-slot="settings-row-description" className="text-[13px] leading-[1.5] text-muted-foreground">
            {description}
          </small>
        )}
      </div>
      {children && <div className={cn("flex shrink-0 items-center gap-1.5", controlClassName)}>{children}</div>}
    </div>
  );
}

/** Full-width slot inside a group (forms, QR panels, lists). */
export function SettingsBlock({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("grid gap-2 px-0.5 py-3", className)}>{children}</div>;
}

/** Flat settings collection: sibling rows are separated without becoming a stack of cards. */
export function SettingsList({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={cn("grid divide-y divide-border/70", className)}>{children}</div>;
}

export function SettingsListItem({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("px-0.5 py-2.5", className)} {...props} />;
}

function flattenSections(children: React.ReactNode): React.ReactNode[] {
  return React.Children.toArray(children).flatMap((child) => {
    if (React.isValidElement<{ children?: React.ReactNode }>(child) && child.type === React.Fragment) {
      return flattenSections(child.props.children);
    }
    return [child];
  });
}

/** Places real separators between settings sections instead of wrapping each section in a card. */
export function SettingsSectionStack({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const sections = flattenSections(children).filter(Boolean);

  return (
    <div
      data-slot="settings-section-stack"
      className={cn(
        "grid h-full min-h-0 content-start [&>[data-slot=settings-group]:first-child_[data-slot=settings-group-description]]:text-ui-md [&>[data-slot=settings-group]:first-child_[data-slot=settings-group-title]]:text-[22px] [&>[data-slot=settings-group]:first-child_[data-slot=settings-group-title]]:font-bold [&>[data-slot=settings-group]:only-child]:h-full [&>[data-slot=settings-group]:only-child]:min-h-0 [&>[data-slot=settings-group]:only-child]:grid-rows-[auto_minmax(0,1fr)]",
        className,
      )}
    >
      {sections.map((section, index) => (
        <React.Fragment key={React.isValidElement(section) && section.key != null ? String(section.key) : index}>
          {index > 0 && <Separator className="my-3.5 bg-border/70" />}
          {section}
        </React.Fragment>
      ))}
    </div>
  );
}


/**
 * 一个表单字段:标签 + 说明 + 控件。
 *
 * 抽出来是因为那串 `[&>span]:… [&_small]:…` 在每个 label 上抄了一遍 —— 抄到第三遍时,
 * 三处的字号已经开始各说各的。
 */
export function SettingsField({
  label,
  description,
  className,
  children,
}: {
  label: string;
  description?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <label className={cn("grid min-w-0 gap-1.5", className)}>
      <span className="text-[15px] font-semibold leading-[1.35] text-foreground">{label}</span>
      {description && <small className="text-[13px] leading-[1.5] text-muted-foreground">{description}</small>}
      {children}
    </label>
  );
}

/**
 * 表单的可读宽度上限。
 *
 * 一个用户名输入框铺满 900px 是没道理的 —— 眼睛要从标签一路扫到光标。设置页此前所有表单
 * 都跟着容器走,窗口越宽越难填。
 */
export function SettingsForm({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("grid max-w-[42rem] gap-3", className)}>{children}</div>;
}
