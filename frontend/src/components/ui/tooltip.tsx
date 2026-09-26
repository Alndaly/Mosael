"use client"

import * as React from "react"
import * as TooltipPrimitive from "@radix-ui/react-tooltip"

import { listenKeys } from "@/lib/shortcuts"
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
 * 最近一次输入是不是键盘。**焦点被程序还回来**(关掉菜单、面板时 Radix 把焦点还给触发它的那枚按钮)
 * 也是一次 focus —— 让它出说明的话,那条说明就挂在那枚按钮上,直到失焦;鼠标移到别的按钮上,
 * 旧的那条还在。所以因聚焦而出说明只认键盘切过来的(Tab、方向键),鼠标一动就不算。
 */
let keyboardInput = false
if (typeof document !== "undefined") {
  listenKeys(document, (event) => {
    if (event.key === "Tab" || event.key.startsWith("Arrow")) keyboardInput = true
  }, true)
  const pointer = () => {
    keyboardInput = false
  }
  document.addEventListener("pointerdown", pointer, true)
  document.addEventListener("pointermove", pointer, true)
}

/** 同一时刻只留一条悬停说明:新的一条出来时,上一条收起。 */
let closeOpenHint: (() => void) | null = null

/**
 * 一枚图标按钮的悬停说明:名字一行,补充的一句淡色在下面。
 *
 * 图标按钮只有图形,**名字得在悬停时马上出来**(Provider 的 delayDuration,应用里是 300ms)——
 * 原生 `title` 要停一秒多、样式是系统的,在一排图标上等于没有。读屏的名字仍然是按钮自己的
 * `aria-label`,这里只管看得见的那一份,所以两者都要写。需要外面有一个 TooltipProvider。
 *
 * **只在指针真的停在上面、或键盘切过来时出**(见 keyboardInput),同一时刻只有一条(closeOpenHint)。
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
  const [open, setOpen] = React.useState(false)
  const hovered = React.useRef(false)
  const close = React.useCallback(() => setOpen(false), [])
  React.useEffect(() => {
    if (!open) return
    if (closeOpenHint && closeOpenHint !== close) closeOpenHint()
    closeOpenHint = close
    return () => {
      if (closeOpenHint === close) closeOpenHint = null
    }
  }, [open, close])
  return (
    <Tooltip
      open={open}
      onOpenChange={(next) => {
        if (!next) setOpen(false)
        else if (hovered.current || keyboardInput) setOpen(true)
      }}
    >
      <TooltipTrigger
        asChild
        onPointerEnter={() => {
          hovered.current = true
        }}
        onPointerLeave={() => {
          hovered.current = false
          setOpen(false)
        }}
      >
        {children}
      </TooltipTrigger>
      <TooltipContent side={side} data-hint="" className="max-w-64 leading-relaxed">
        <span className="block">{label}</span>
        {hint && hint !== label ? <span className="block text-muted-foreground">{hint}</span> : null}
      </TooltipContent>
    </Tooltip>
  )
}

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider, Hint }
