import React from "react";

import { CONTROL_HEIGHT } from "@/components/ui/control-size";
import { Truncate } from "@/components/ui/truncate";
import { cn } from "@/lib/utils";

/**
 * 管理页的版式零件:**一种节头、一种卡片、一种行**,各个 tab 共用。
 *
 * 此前这一页混着三套:设置页的 SettingsGroup(20px 节标题)、被外面一串 `[&_…]` 选择器压成 16px
 * 的同一个组件、以及统计页式的卡片 —— 同一页上三种标题字号、三种行高。字号只有三档:
 *
 *   节标题   text-ui-md  semibold     一节一个,说明最多一句
 *   卡片标题 text-ui-sm  semibold     图表卡片里
 *   行       text-ui-sm  medium / 次要信息 text-ui-xs muted
 *
 * 行只有一种:引擎、模型这类「一个东西」的行也是 AdminRow,只是多用几个插槽(名字旁的元信息、
 * 说明下面的状态行、横贯整行的进度)。它们此前在设置页用另一套 SettingsItemRow(20px 行距、
 * text-ui-md 标签);搬来管理页时没有再带一套过来,否则同一页上又是两种行高。
 *
 * **节与节只由父容器的 gap 隔开,谁都不带 h-full / min-h-0。** 旧页面的重叠就出在这里:
 * 注册那一节是一个 `h-full min-h-0` 的网格,放进一个**定了高度、会滚动**的网格里当一行 ——
 * `min-h-0` 让这一行的最小贡献变成 0,内容一超出视口,这一行就被压成 0 高,下一节画在它身上。
 */

/** 一节:标题 + 一句说明 + 右侧动作,下面是内容。 */
export function AdminSection({
  id,
  title,
  count,
  description,
  actions,
  children,
}: {
  id: string;
  title: string;
  /** 这一节有几条(账户数)。和页头的计数同一个长相,贴着标题,不孤零零地挂在右边。 */
  count?: number;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  const headingId = `admin-section-${id}`;
  return (
    <section data-admin-section={id} aria-labelledby={headingId} className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3">
      <header className="flex min-w-0 flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div className="grid min-w-0 gap-1">
          <div className="flex items-center gap-2">
            <h2 id={headingId} className="m-0 text-ui-md font-semibold leading-snug">
              {title}
            </h2>
            {count !== undefined && (
              <span className="rounded-md bg-secondary px-1.5 py-0.5 text-ui-xs tabular-nums text-muted-foreground">{count}</span>
            )}
          </div>
          {description && <p className="m-0 max-w-2xl text-ui-sm leading-relaxed text-muted-foreground">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </header>
      {children}
    </section>
  );
}

/** 卡片外壳:行与行之间一条分割线。 */
export const ADMIN_CARD = "grid min-w-0 grid-cols-[minmax(0,1fr)] divide-y divide-divider overflow-hidden rounded-lg border border-border bg-panel";

/** 卡片里的一行:左边主次两行字,右边控件。 */
export function AdminRow({
  label,
  description,
  leading,
  meta,
  tags,
  notes,
  footer,
  children,
  className,
  stacked = false,
}: {
  label: React.ReactNode;
  description?: React.ReactNode;
  leading?: React.ReactNode;
  /** 名字后面的小字,逐项用「·」隔开(引擎族、大小)。假值自动跳过。 */
  meta?: readonly React.ReactNode[];
  /** 名字后面的安静标签,用 AdminTag。 */
  tags?: React.ReactNode;
  /** 说明下面按状态出现的几行(检查中、跑不起来的原因、失败原因),用 AdminRowNote。 */
  notes?: React.ReactNode;
  /** 横贯整行、在最下面的一格 —— 下载进度条。 */
  footer?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  /** 控件放到字下面、占满整行 —— 给要写一段话的控件(多行文本框)。放在右边那一格它会被挤成一条窄缝。 */
  stacked?: boolean;
}) {
  if (stacked) {
    return (
      <div data-admin-row className={cn("grid min-w-0 gap-2 px-4 py-3", className)}>
        <div className="grid min-w-0 gap-0.5">
          <span className="min-w-0 text-ui-sm font-medium">{label}</span>
          {description && <span className="min-w-0 text-ui-xs leading-normal text-muted-foreground">{description}</span>}
        </div>
        {children}
      </div>
    );
  }
  const metaItems = (meta ?? []).filter((item) => item !== null && item !== undefined && item !== false && item !== "");
  // flex-wrap 只为 footer:文字那一格是 flex-1 + min-w-0(基准 0),右边控件不收缩,两者永远在同一行;
  // 只有 basis-full 的 footer 会折到下面,于是进度条不必另起一套两层的结构。
  return (
    <div data-admin-row className={cn("flex min-h-14 min-w-0 flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3", className)}>
      {leading}
      <div className="grid min-w-0 flex-1 gap-0.5">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
          <Truncate className="text-ui-sm font-medium">{label}</Truncate>
          {metaItems.length > 0 && (
            <span data-admin-row-meta className="text-ui-xs tabular-nums text-muted-foreground">
              {metaItems.map((item, index) => (
                <React.Fragment key={index}>
                  {index > 0 && " · "}
                  {item}
                </React.Fragment>
              ))}
            </span>
          )}
          {tags}
        </div>
        {description && (
          <span data-admin-row-description className="min-w-0 text-ui-xs leading-normal text-muted-foreground">
            {description}
          </span>
        )}
        {notes}
      </div>
      {children && (
        <div data-admin-row-control className="flex shrink-0 items-center gap-2">
          {children}
        </div>
      )}
      {footer && (
        <div data-admin-row-footer className="min-w-0 basis-full">
          {footer}
        </div>
      )}
    </div>
  );
}

const NOTE_TONE = {
  muted: "text-muted-foreground",
  foreground: "text-foreground",
  destructive: "text-destructive",
} as const;

/** AdminRow 说明下面的一行状态。和说明同一档字号,只换颜色 —— 失败原因不该比说明还大。 */
export function AdminRowNote({
  tone = "muted",
  icon,
  children,
}: {
  tone?: keyof typeof NOTE_TONE;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <span
      data-admin-row-note
      data-tone={tone}
      className={cn("flex min-w-0 items-center gap-1.5 text-ui-xs leading-normal [&>svg]:shrink-0", NOTE_TONE[tone])}
    >
      {icon}
      {children}
    </span>
  );
}

const STATE_TONE = {
  success: "font-medium text-success",
  muted: "text-muted-foreground",
} as const;

/**
 * AdminRow 右边**不是按钮**时的那个状态(「已安装」、转圈 + 百分比)。
 *
 * 高度取 CONTROL_HEIGHT.sm,和同一格里的 `<Button size="sm">` 一样高 —— 一行从「下载」变成
 * 「已安装」时,整行不跳。
 */
export function AdminRowState({
  tone = "muted",
  icon,
  children,
}: {
  tone?: keyof typeof STATE_TONE;
  icon?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <span
      data-admin-row-state
      data-tone={tone}
      className={cn(CONTROL_HEIGHT.sm, "inline-flex items-center gap-1.5 text-ui-sm tabular-nums [&>svg]:shrink-0", STATE_TONE[tone])}
    >
      {icon}
      {children}
    </span>
  );
}

const TAG_TONE = {
  neutral: "bg-secondary text-muted-foreground",
  warning: "bg-[color-mix(in_srgb,var(--warning)_14%,transparent)] text-warning",
} as const;

/** 名字旁的安静标签:语义色淡底的小圆角,不描边、不大写。 */
export function AdminTag({ tone = "neutral", children }: { tone?: keyof typeof TAG_TONE; children: React.ReactNode }) {
  return (
    <span
      data-admin-tag
      data-tone={tone}
      className={cn("inline-flex shrink-0 items-center rounded-full px-1.5 text-ui-2xs font-medium leading-5", TAG_TONE[tone])}
    >
      {children}
    </span>
  );
}
