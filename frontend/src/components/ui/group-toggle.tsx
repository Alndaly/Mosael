import * as React from "react"
import { ChevronRight } from "lucide-react"

import { Truncate } from "@/components/ui/truncate"
import { cn } from "@/lib/utils"

/**
 * 列表里一组的折叠标题:整行、左边一个会转的箭头、名字(截断时悬停看全文)、右头这一组有几项。12px 中等字重次要色,
 * 悬停显出次级底色 —— 它是列表里的一行,不是表单里那种「高级」开关(那个是 Disclosure:一行字、没有底色)。
 *
 * 此前 AI Studio 会话列表的分组标题和「来自别处」那一组各手搓一颗原生按钮(同一串 class 抄了两遍)。可以套在
 * ContextMenuTrigger 里(转发 ref)。开合由调用方管:给 `open`,点了调 `onClick`;`aria-expanded` 这里给。
 */
export const GroupToggle = React.forwardRef<
  HTMLButtonElement,
  Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "children" | "className"> & {
    open: boolean
    label: React.ReactNode
    /** 这一组有几项,摆在右头。 */
    count?: number
    /** 只给排版用(外边距)。 */
    className?: string
  }
>(({ open, label, count, className, type = "button", ...props }, ref) => (
  <button
    ref={ref}
    type={type}
    aria-expanded={open}
    data-group-toggle=""
    className={cn(
      "flex w-full cursor-pointer items-center gap-1 rounded-md border-0 bg-transparent px-1.5 py-1 text-left text-ui-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset",
      className,
    )}
    {...props}
  >
    <ChevronRight size={12} aria-hidden className={cn("shrink-0 transition-transform duration-100 motion-reduce:transition-none", open && "rotate-90")} />
    <Truncate className="flex-1">{label}</Truncate>
    {count !== undefined && <span className="shrink-0 tabular-nums">{count}</span>}
  </button>
))
GroupToggle.displayName = "GroupToggle"
