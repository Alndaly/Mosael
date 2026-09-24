import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * 检查器里的一节:上面一道分隔线,一行标题(右边可挂一个动作),下面是内容。
 *
 * 属性、调色、花字、外观几块面板此前各写各的 `border-t pt-*`,于是节奏各不相同(pt-4 / pt-2.5),
 * 调色页还在「作用于」那行底下自带一道 border-b —— 紧跟着「风格预设」的 border-t,两道线夹出
 * 一条空带。**分隔线只由节画、只画在节的上边**:面板的第一行(属性页的 `<dl>`、调色页的作用
 * 对象)不是节,不带线,第一节的上边线就是它和下面的分界。
 */
export function InspectorSection({
  title,
  action,
  className,
  children,
}: {
  title?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <section className={cn("grid gap-3 border-t border-border pt-4", className)}>
      {(title || action) && (
        <div className="flex min-w-0 items-center justify-between gap-2">
          {title && <h3 className="m-0 inline-flex items-center gap-1.5 text-ui-sm font-semibold text-muted-foreground">{title}</h3>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
