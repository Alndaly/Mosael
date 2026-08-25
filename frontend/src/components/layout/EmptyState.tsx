import React from "react";

import { cn } from "@/lib/utils";

/**
 * 「这里还没有东西」的统一说法。
 *
 * **两个尺寸,不是两个组件**:整页/整块用 `full`(默认),弹出层、窄侧栏、对话框里的小分区用
 * `compact`。此前小面板各自糊一行居中灰字 —— 三处三个样子,而读者从"长得不一样"读出的是
 * 「这里坏了」,不是「这里还没有东西」。
 *
 * `body` 可以省:一句标题足够时不必硬凑第二句。有下一步动作就给 `action` —— 空状态最有价值的
 * 那一半是"接下来做什么",而不是"这里是空的"。
 */
export function EmptyState({
  icon,
  title,
  body,
  badge,
  action,
  size = "full",
  className,
}: {
  icon: React.ReactNode;
  title: string;
  body?: string;
  badge?: string;
  action?: React.ReactNode;
  size?: "full" | "compact";
  className?: string;
}) {
  const compact = size === "compact";
  return (
    <div
      className={cn(
        // `max-w` 是**上限不是宽度**,但它挡不住比它更窄的容器 —— 260px 的空态放进 258px 的
        // 侧栏就溢出 10px,而那 10px 会让整页能左右滑。`w-full` 让它先服从容器,
        // `break-words` 让里面的长 URL(报错文案里全是)断得开而不是硬撑。
        "empty-state m-auto grid w-full justify-items-center break-words text-center [overflow-wrap:anywhere]",
        compact
          ? "max-w-[260px] gap-1 px-3 py-4 [&_h2]:m-0 [&_h2]:text-ui-sm [&_h2]:font-[620] [&_p]:m-0 [&_p]:text-ui-xs [&_p]:leading-[1.5] [&_p]:text-muted-foreground"
          : "max-w-[420px] gap-2 px-5 py-8 [&_h2]:mt-0.5 [&_h2]:text-sm [&_h2]:font-[650] [&_p]:mb-1.5 [&_p]:mt-0 [&_p]:text-ui-md [&_p]:leading-[1.55] [&_p]:text-muted-foreground",
        className,
      )}
    >
      <div
        className={cn(
          "grid place-items-center rounded-lg border border-[color-mix(in_oklab,var(--primary)_18%,var(--border))] bg-[color-mix(in_oklab,var(--primary)_6%,var(--panel))] text-primary",
          compact ? "h-8 w-8" : "h-11 w-11",
        )}
      >
        {icon}
      </div>
      {badge && (
        <span className="rounded-full border border-border bg-secondary px-[9px] py-px text-ui-xs font-semibold text-muted-foreground">
          {badge}
        </span>
      )}
      <h2>{title}</h2>
      {body && <p>{body}</p>}
      {action}
    </div>
  );
}
