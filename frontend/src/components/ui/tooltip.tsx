"use client"

import * as React from "react"
import * as TooltipPrimitive from "@radix-ui/react-tooltip"

import { cn } from "@/lib/utils"

import { FLOATING_COLLISION_PADDING } from "./floating"

const TooltipProvider = TooltipPrimitive.Provider

const Tooltip = TooltipPrimitive.Root

const TooltipTrigger = TooltipPrimitive.Trigger

const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 4, ...props }, ref) => (
  <TooltipPrimitive.Portal>
    <TooltipPrimitive.Content
      ref={ref}
      data-tooltip=""
      sideOffset={sideOffset}
      collisionPadding={FLOATING_COLLISION_PADDING}
      className={cn(
        "z-50 overflow-hidden rounded-md border border-border bg-popover px-3 py-1.5 text-xs text-popover-foreground animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 origin-(--radix-tooltip-content-transform-origin)",
        className
      )}
      {...props}
    />
  </TooltipPrimitive.Portal>
))
TooltipContent.displayName = TooltipPrimitive.Content.displayName

/**
 * 一枚图标按钮的悬停说明:名字一行,补充的一句淡色在下面。
 *
 * 图标按钮只有图形,**名字得在悬停时马上出来**(Provider 的 delayDuration,应用里是 300ms)——
 * 原生 `title` 要停一秒多、样式是系统的,在一排图标上等于没有。读屏的名字仍然是按钮自己的
 * `aria-label`,这里只管看得见的那一份,所以两者都要写。需要外面有一个 TooltipProvider。
 */
function Hint({
  label,
  hint,
  side = "top",
  children,
}: {
  label: string
  hint?: string
  side?: "top" | "bottom" | "left" | "right"
  children: React.ReactNode
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side={side} data-hint="" className="max-w-64 leading-relaxed">
        <span className="block">{label}</span>
        {hint && hint !== label ? <span className="block text-muted-foreground">{hint}</span> : null}
      </TooltipContent>
    </Tooltip>
  )
}

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider, Hint }
