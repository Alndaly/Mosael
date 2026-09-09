"use client"

import * as React from "react"
import * as DialogPrimitive from "@radix-ui/react-dialog"
import { X } from "lucide-react"

import { MODAL_OVERLAY, MODAL_TITLE, MODAL_DESCRIPTION } from "./floating"
import { useModalTeardownGuard } from "@/lib/modalTeardownGuard"
import { cn } from "@/lib/utils"

/**
 * 贴着屏幕一侧滑出的面板。
 *
 * 和 Dialog 的区别不是外观,是**它和背后那一屏的关系**:对话框问一件事,答完就走,所以它
 * 落在正中央、把注意力全收走;侧栏是**一直开着看的一列东西**(讨论、活动、检查器),用户
 * 要一边看它一边看画布 —— 摆在正中央就等于把它要讲的那张画布盖住了。
 *
 * 底下仍然铺一层遮罩:侧栏是模态的,焦点、Esc、点外面关闭这些都交给 Radix Dialog,这里只换
 * 位置和进出方向。
 */
const Sheet = DialogPrimitive.Root
const SheetTrigger = DialogPrimitive.Trigger
const SheetClose = DialogPrimitive.Close
const SheetPortal = DialogPrimitive.Portal

const SIDES = {
  right: "inset-y-0 right-0 h-full border-l data-[state=open]:slide-in-from-right data-[state=closed]:slide-out-to-right",
  left: "inset-y-0 left-0 h-full border-r data-[state=open]:slide-in-from-left data-[state=closed]:slide-out-to-left",
} as const

const SheetContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
    side?: keyof typeof SIDES
    showClose?: boolean
  }
>(({ className, children, side = "right", showClose = true, ...props }, ref) => {
  // 兜底撤销 body 上的模态副作用(pointer-events / 滚动锁),和 Dialog 同一个理由。见 hook 注释。
  useModalTeardownGuard()
  return (
    <SheetPortal>
      <DialogPrimitive.Overlay
        className={cn(
          MODAL_OVERLAY,
          "duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0 motion-reduce:animate-none",
        )}
      />
      <DialogPrimitive.Content
        ref={ref}
        data-slot="sheet-content"
        className={cn(
          "[.is-desktop_&]:[-webkit-app-region:no-drag] fixed z-50 grid min-h-0 w-[min(30rem,calc(100vw-2rem))] grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)]",
          "modal-surface border-[var(--modal-border)] bg-[var(--modal-surface)] text-popover-foreground shadow-[var(--shadow-modal)]",
          "duration-250 data-[state=open]:animate-in data-[state=closed]:animate-out motion-reduce:animate-none motion-reduce:transition-none",
          SIDES[side],
          className,
        )}
        {...props}
      >
        {children}
        {showClose && (
          <DialogPrimitive.Close className="absolute right-4 top-4 z-20 grid size-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none">
            <X className="h-4 w-4" />
            <span className="sr-only">Close</span>
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Content>
    </SheetPortal>
  )
})
SheetContent.displayName = DialogPrimitive.Content.displayName

/** 标题区。右上角留出关闭键的位置,标题自己不去撞它。 */
const SheetHeader = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("grid gap-1.5 border-b border-divider px-5 py-4 pr-14", className)} {...props} />
)
SheetHeader.displayName = "SheetHeader"

const SheetTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title ref={ref} className={cn(MODAL_TITLE, "text-ui-md", className)} {...props} />
))
SheetTitle.displayName = DialogPrimitive.Title.displayName

const SheetDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description ref={ref} className={cn(MODAL_DESCRIPTION, "text-ui-xs", className)} {...props} />
))
SheetDescription.displayName = DialogPrimitive.Description.displayName

export { Sheet, SheetTrigger, SheetClose, SheetPortal, SheetContent, SheetHeader, SheetTitle, SheetDescription }
