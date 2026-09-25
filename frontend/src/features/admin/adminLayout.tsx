import React from "react";

import { cn } from "@/lib/utils";

/**
 * 管理页的版式零件:**一种节头、一种卡片、一种行**,三个 tab 共用。
 *
 * 此前这一页混着三套:设置页的 SettingsGroup(20px 节标题)、被外面一串 `[&_…]` 选择器压成 16px
 * 的同一个组件、以及统计页式的卡片 —— 同一页上三种标题字号、三种行高。字号只有三档:
 *
 *   节标题   text-ui-md  semibold     一节一个,说明最多一句
 *   卡片标题 text-ui-sm  semibold     图表卡片里
 *   行       text-ui-sm  medium / 次要信息 text-ui-xs muted
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
  children,
  className,
}: {
  label: React.ReactNode;
  description?: React.ReactNode;
  leading?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <div data-admin-row className={cn("flex min-h-14 min-w-0 items-center gap-3 px-4 py-3", className)}>
      {leading}
      <div className="grid min-w-0 flex-1 gap-0.5">
        <span className="min-w-0 truncate text-ui-sm font-medium">{label}</span>
        {description && <span className="min-w-0 text-ui-xs leading-normal text-muted-foreground">{description}</span>}
      </div>
      {children && <div className="flex shrink-0 items-center gap-2">{children}</div>}
    </div>
  );
}
