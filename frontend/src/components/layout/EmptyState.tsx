import React from "react";

import { cn } from "@/lib/utils";

/**
 * 「这里还没有东西」的统一说法。
 *
 * **三个尺寸,不是三个组件**:整页用 `full`(默认),设置页那种"一节的正文空着"用 `section`,
 * 弹出层、窄侧栏、对话框里的小分区用 `compact`。此前小面板各自糊一行居中灰字 —— 三处三个
 * 样子,而读者从"长得不一样"读出的是「这里坏了」,不是「这里还没有东西」。
 *
 * `section` 这一档是补出来的:设置页拿 `full` 用,于是「还没有机器人」是 20px 粗体、配一个
 * 64px 的图标砖,而它上面那个真正的节标题也才 24px —— 一句"这里是空的"和整节的标题一样重,
 * 眼睛先看到的是空态。它比整页那一档轻一级:标题回到正文的字号、图标砖收到 44px。
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
  size?: "full" | "section" | "compact";
  className?: string;
}) {
  const compact = size === "compact";
  const section = size === "section";
  return (
    <div
      className={cn(
        // `max-w` 是**上限不是宽度**,但它挡不住比它更窄的容器 —— 260px 的空态放进 258px 的
        // 侧栏就溢出 10px,而那 10px 会让整页能左右滑。`w-full` 让它先服从容器,
        // `break-words` 让里面的长 URL(报错文案里全是)断得开而不是硬撑。
        "empty-state m-auto grid w-full justify-items-center break-words text-center [overflow-wrap:anywhere]",
        compact &&
          "max-w-[260px] gap-1 px-3 py-4 [&_h2]:m-0 [&_h2]:text-ui-sm [&_h2]:font-[620] [&_p]:m-0 [&_p]:text-ui-xs [&_p]:leading-[1.5] [&_p]:text-muted-foreground",
        section &&
          "max-w-[380px] gap-2 px-5 py-6 [&_h2]:m-0 [&_h2]:mt-1 [&_h2]:text-ui-md [&_h2]:font-[600] [&_p]:m-0 [&_p]:max-w-[36ch] [&_p]:text-ui-sm [&_p]:leading-[1.6] [&_p]:text-muted-foreground",
        !compact && !section &&
          "max-w-[480px] gap-3 px-6 py-10 [&_h2]:mt-2 [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:tracking-tight [&_p]:mb-3 [&_p]:mt-0 [&_p]:max-w-[40ch] [&_p]:text-ui-md [&_p]:leading-relaxed [&_p]:text-muted-foreground",
        className,
      )}
    >
      <div
        className={cn(
          "grid place-items-center bg-accent text-primary",
          compact && "h-8 w-8 rounded-lg",
          section && "h-11 w-11 rounded-xl [&_svg]:size-5",
          !compact && !section && "h-16 w-16 rounded-2xl [&_svg]:size-7",
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
