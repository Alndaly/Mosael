"use client"

import * as React from "react"
import * as PopoverPrimitive from "@radix-ui/react-popover"

import { FLOATING_SURFACE, FLOATING_MOTION } from "./floating"

import { cn } from "@/lib/utils"

/**
 * 注意:**放在 Dialog 里、且内容需要滚动的 Popover 必须显式传 `modal`。**
 *
 * Radix Popover 的 `modal` 默认是 false(DropdownMenu / ContextMenu 默认是 true,所以它们没这个问题)。
 * Dialog 用 react-remove-scroll 锁背景滚动,而它只放行自己 shard(DialogContent)之内的滚轮事件;
 * PopoverContent 走下面的 Portal 渲染到 body,天然落在 shard 之外 —— 于是列表明明是 overflow-y-auto、
 * 滚动条也画出来了,滚轮却完全无效。
 *
 * 故障特征很好认:**滚轮无效,但拖滚动条和按方向键都正常**。见 Combobox / SearchableSelect,
 * 这两个可搜索下拉已经默认带上 modal。
 */
const Popover = PopoverPrimitive.Root

const PopoverTrigger = PopoverPrimitive.Trigger

const PopoverAnchor = PopoverPrimitive.Anchor
const PopoverClose = PopoverPrimitive.Close

const PopoverContent = React.forwardRef<
  React.ElementRef<typeof PopoverPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof PopoverPrimitive.Content>
>(({ className, align = "center", sideOffset = 6, ...props }, ref) => (
  <PopoverPrimitive.Portal>
    <PopoverPrimitive.Content
      ref={ref}
      align={align}
      sideOffset={sideOffset}
      className={cn(
        FLOATING_SURFACE, FLOATING_MOTION,
        "z-50 w-72 max-w-[calc(100vw-1rem)] p-4 outline-none",
        className
      )}
      {...props}
    />
  </PopoverPrimitive.Portal>
))
PopoverContent.displayName = PopoverPrimitive.Content.displayName

export { Popover, PopoverTrigger, PopoverContent, PopoverAnchor, PopoverClose }
