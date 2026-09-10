import React from "react";

import { EmptyState } from "@/components/layout/EmptyState";
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
    <section data-slot="settings-group" className={cn("@container/settings grid gap-1", className)}>
      {/* 动作**对齐整个抬头的竖向中心**,不是对齐标题那一行,也不是对齐整块的底边。
          三种都试过:`items-end` 在说明一长时把按钮拖到最后一行旁边,看着像那句话的一部分;
          `items-start` 则在说明有两三行时把按钮顶在最上面,右边空出一大块。
          `items-center` 两头都不沾 —— 按钮始终落在这一节抬头的视觉重心上。 */}
      <header
        data-slot="settings-group-header"
        className={cn(
          "flex flex-wrap items-start justify-between gap-4 px-0.5",
          hasContent && "pb-2",
        )}
      >
        <div className="min-w-0">
          <h2
            data-slot="settings-group-title"
            className="m-0 text-xl font-semibold leading-snug tracking-tight"
          >
            {title}
          </h2>
          {description && (
            <p
              data-slot="settings-group-description"
              className="mb-0 mt-1.5 max-w-2xl text-ui-md leading-[1.55] text-muted-foreground"
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
          className={cn("grid [&>*+*]:border-t [&>*+*]:border-divider", contentClassName)}
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
    <div
      id={id}
      data-slot="settings-row"
      className={cn("grid grid-cols-1 items-start gap-3 px-0.5 py-5 @min-[620px]/settings:grid-cols-[minmax(0,1fr)_auto] @min-[620px]/settings:items-center @min-[620px]/settings:gap-8", className)}
    >
      <div className="grid min-w-0 gap-1">
        <span data-slot="settings-row-label" className="text-ui-md font-medium leading-relaxed">{label}</span>
        {description && (
          <small data-slot="settings-row-description" className="text-ui-sm leading-[1.5] text-muted-foreground">
            {description}
          </small>
        )}
      </div>
      {children && <div className={cn("flex min-w-0 flex-wrap items-center gap-2", controlClassName)}>{children}</div>}
    </div>
  );
}

/**
 * 设置行右边那一格的**标准宽度**。
 *
 * 那一格是 `auto` 列 —— 控件要多宽就多宽。于是各个 tab 各写各的:实测过一遍是
 * 320 / 260 / 200 / 180 六种宽度并存,而它们在版面上是同一个位置。一个 tab 切到另一个 tab,
 * 右边那一列会跟着跳,看起来像每一页的表单都是另一套刻度。
 *
 * 文字类的字段(地址、备注、下拉选名字)一律走这个宽度。**真的只装得下几个字符的不走** ——
 * 0–10 的重试次数、1.0× 的语速,给它 280px 只会在一个数字后面拖一条空槽;那种就地写死,
 * 并且写清楚为什么。
 */
export const SETTINGS_FIELD_WIDTH = "w-[280px] max-w-full";

/** Full-width slot inside a group (forms, QR panels, lists). */
export function SettingsBlock({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div data-slot="settings-block" className={cn("grid gap-4 px-0.5 py-5", className)}>{children}</div>;
}

/**
 * **一整节的正文空着**时用它 —— 飞书没有机器人、音色库没有音色、计价没有规则。
 *
 * 两件事收在这里,而不是每个调用点各写一遍:
 *
 * 1. **占住一片地方,并在里面居中。** 此前空态直接摆进 SettingsBlock,而 Block 是内容高度 ——
 *    于是「还没有机器人」贴在标题下面,底下空着三百多像素(实测 366px)。有两处试过写
 *    `h-full min-h-0`,不管用:SettingsSectionStack 是 `content-start`,行高按内容算,
 *    `h-full` 回头去问一个由内容决定的高度,等于没写。
 *
 *    这里给的是**下限高度 + 居中**,而不是真的撑满剩余空间。撑满要求从可滚容器到这一层
 *    每一级都交出确定高度,而分节堆叠**本来就该把各节顶到上面**(多节的设置页正是靠它)。
 *    为一个空态把那条规则改掉,代价落在所有正常的页面上。
 *
 * 2. **用 section 那一档尺寸。** 见 EmptyState 的说明:整页那一档在设置页里比节标题还重。
 */
export function SettingsEmpty({ className, ...props }: React.ComponentProps<typeof EmptyState>) {
  return (
    <div
      data-slot="settings-empty"
      className={cn("grid min-h-[clamp(220px,38vh,360px)] place-content-center place-items-center", className)}
    >
      <EmptyState size="section" {...props} />
    </div>
  );
}

/** Block 内的小标题不自带外边距；它与后续内容的距离由 SettingsBlock 的 gap 统一控制。 */
export function SettingsBlockTitle({ className, ...props }: React.ComponentProps<"h3">) {
  return (
    <h3
      data-slot="settings-block-title"
      className={cn("m-0 flex items-center gap-2 text-ui-md font-semibold", className)}
      {...props}
    />
  );
}

/** Flat settings collection: sibling rows are separated without becoming a stack of cards. */
export function SettingsList({
  children,
  className,
  scrollable = false,
}: {
  children: React.ReactNode;
  className?: string;
  scrollable?: boolean;
}) {
  return (
    <div
      data-slot="settings-list"
      className={cn(
        "grid divide-y divide-divider",
        scrollable && "max-h-80 overflow-y-auto overscroll-contain [scrollbar-gutter:stable]",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** Pure list section: list rows own the vertical edge spacing, so no outer block padding is added. */
export function SettingsListBlock({
  children,
  className,
  toolbar,
}: {
  children: React.ReactNode;
  className?: string;
  toolbar?: React.ReactNode;
}) {
  return (
    <div data-slot="settings-list-block" className={cn("grid min-h-0 gap-1.5", className)}>
      {toolbar && (
        <div data-slot="settings-list-toolbar" className="px-0.5 pt-3">
          {toolbar}
        </div>
      )}
      <SettingsList>{children}</SettingsList>
    </div>
  );
}

export function SettingsListItem({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="settings-list-item" className={cn("px-0.5 py-5", className)} {...props} />;
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
        "grid h-full min-h-0 content-start has-[>[data-slot=settings-group]:only-child]:content-stretch [&>[data-slot=settings-group]:first-child_[data-slot=settings-group-description]]:text-ui-md [&>[data-slot=settings-group]:first-child_[data-slot=settings-group-title]]:text-2xl [&>[data-slot=settings-group]:first-child_[data-slot=settings-group-title]]:font-semibold [&>[data-slot=settings-group]:only-child]:h-full [&>[data-slot=settings-group]:only-child]:min-h-0 [&>[data-slot=settings-group]:only-child]:grid-rows-[auto_minmax(0,1fr)]",
        className,
      )}
    >
      {sections.map((section, index) => (
        <React.Fragment
          key={`settings-section-${index}-${React.isValidElement(section) && section.key != null ? String(section.key) : ""}`}
        >
          {/* 分割线属于上一节的收尾：紧贴上一节，只用下边距为下一节标题留出层级。
              如果这里使用 my-*, 会和上一节最后一行的 py-3 叠加，造成视觉上的下宽上窄。 */}
          {index > 0 && <Separator className="mb-7 mt-3 bg-divider" />}
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
    <label data-slot="settings-field" className={cn("grid min-w-0 gap-1.5", className)}>
      <span className="text-ui-md font-medium leading-relaxed text-foreground">{label}</span>
      {description && <small className="text-ui-sm leading-[1.5] text-muted-foreground">{description}</small>}
      {children}
    </label>
  );
}

/** 表单负责占满设置内容列；字段是否并排由调用方按信息关系显式组织。 */
export function SettingsForm({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div data-slot="settings-form" className={cn("grid w-full gap-5", className)}>{children}</div>;
}
