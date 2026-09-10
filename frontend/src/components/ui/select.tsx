"use client"

import * as React from "react"
import * as SelectPrimitive from "@radix-ui/react-select"
import { Check, ChevronDown, ChevronUp } from "lucide-react"

import { FIELD_TRIGGER_CLASS, FIELD_TRIGGER_CHEVRON } from "@/components/ui/field-trigger"
import { FLOATING_SURFACE, FLOATING_MOTION, MENU_SEPARATOR } from "./floating"

import { cn } from "@/lib/utils"

const Select = SelectPrimitive.Root

const SelectGroup = SelectPrimitive.Group

const SelectValue = SelectPrimitive.Value

const SelectTrigger = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Trigger
    ref={ref}
    className={cn(FIELD_TRIGGER_CLASS, className)}
    {...props}
  >
    {children}
    <SelectPrimitive.Icon asChild>
      <ChevronDown className={FIELD_TRIGGER_CHEVRON} />
    </SelectPrimitive.Icon>
  </SelectPrimitive.Trigger>
))
SelectTrigger.displayName = SelectPrimitive.Trigger.displayName

const SelectScrollUpButton = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.ScrollUpButton>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollUpButton>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.ScrollUpButton
    ref={ref}
    className={cn(
      "flex cursor-default items-center justify-center py-1",
      className
    )}
    {...props}
  >
    <ChevronUp className="h-4 w-4" />
  </SelectPrimitive.ScrollUpButton>
))
SelectScrollUpButton.displayName = SelectPrimitive.ScrollUpButton.displayName

const SelectScrollDownButton = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.ScrollDownButton>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollDownButton>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.ScrollDownButton
    ref={ref}
    className={cn(
      "flex cursor-default items-center justify-center py-1",
      className
    )}
    {...props}
  >
    <ChevronDown className="h-4 w-4" />
  </SelectPrimitive.ScrollDownButton>
))
SelectScrollDownButton.displayName =
  SelectPrimitive.ScrollDownButton.displayName

const SelectContent = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(({ className, children, position = "popper", ...props }, ref) => (
  <SelectPrimitive.Portal>
    <SelectPrimitive.Content
      ref={ref}
      className={cn(
        // 限高两层,缺一不可:Radix 的 available-height 管「不顶出屏幕」,但它允许菜单长到
        // 近千像素(触发器在屏幕底部、向上展开时)——时长区间 4–30s 列成 27 项就是这个下场,
        // 顶部的选项直接跑出窗口外。所以再叠一个固定上限,长列表在菜单内部滚(滚动按钮
        // 是 ScrollUp/DownButton,已在下面挂着)。fallback 100vh 兜住 var 不存在的非 popper 场景。
        FLOATING_SURFACE, FLOATING_MOTION,
        "relative z-50 max-h-[min(20rem,var(--radix-select-content-available-height,100vh))] min-w-[8rem] overflow-y-auto overflow-x-hidden",
        // 菜单**不窄于**字段(对齐好看),但也**不被字段封顶**:此前这里是
        // `max-w-[trigger-width]`,于是任何一个窄字段都会把自己的菜单压成一样窄 ——
        // 配音面板 65px 的引擎格里,「F5-TTS」「Fish Speech S2 Pro」实测显示成
        // 「F5…」「Fi…」。**读不出选项的菜单等于没有菜单**,对齐再齐也没用。
        // 上限交给 Radix 算出来的可用宽度,这样它仍然不会顶出屏幕。
        position === "popper" && "min-w-[var(--radix-select-trigger-width)] max-w-[--radix-select-content-available-width]",
        position === "popper" &&
          "data-[side=bottom]:translate-y-1.5 data-[side=left]:-translate-x-1.5 data-[side=right]:translate-x-1.5 data-[side=top]:-translate-y-1.5",
        className
      )}
      position={position}
      {...props}
    >
      <SelectScrollUpButton />
      <SelectPrimitive.Viewport
        className={cn(
          "p-1.5",
          position === "popper" &&
            "h-[var(--radix-select-trigger-height)] w-full min-w-[var(--radix-select-trigger-width)]"
        )}
      >
        {children}
      </SelectPrimitive.Viewport>
      <SelectScrollDownButton />
    </SelectPrimitive.Content>
  </SelectPrimitive.Portal>
))
SelectContent.displayName = SelectPrimitive.Content.displayName

const SelectLabel = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Label>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Label>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Label
    ref={ref}
    className={cn("px-2 py-1.5 text-sm font-semibold", className)}
    {...props}
  />
))
SelectLabel.displayName = SelectPrimitive.Label.displayName

/**
 * 选项。`description` 是解释"选它会怎样"的副标题。
 *
 * **它必须待在 ItemText 外面。** Radix 把选中项的 ItemText **原样克隆进触发器** —— 副标题
 * 写进 children 的话,那一格就变成两行字,和旁边每一格都不一样高。副标题属于清单,
 * 不属于"当前选了什么"。
 */
const SelectItem = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item> & { description?: React.ReactNode }
>(({ className, children, description, ...props }, ref) => (
  <SelectPrimitive.Item
    ref={ref}
    className={cn(
      "relative flex min-h-9 w-full min-w-0 cursor-default select-none rounded-md py-2 pl-2.5 pr-8 text-ui-sm leading-5 outline-none focus:bg-secondary data-[disabled]:pointer-events-none data-[disabled]:opacity-40 [&>span:last-child]:block [&>span:last-child]:min-w-0 [&>span:last-child]:truncate",
      description ? "flex-col items-start gap-px" : "items-center",
      className
    )}
    {...props}
  >
    <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center">
      <SelectPrimitive.ItemIndicator>
        <Check className="h-4 w-4" />
      </SelectPrimitive.ItemIndicator>
    </span>
    <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    {description && <span className="min-w-0 truncate text-ui-xs text-muted-foreground">{description}</span>}
  </SelectPrimitive.Item>
))
SelectItem.displayName = SelectPrimitive.Item.displayName

const SelectSeparator = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Separator
    ref={ref}
    className={cn(MENU_SEPARATOR, className)}
    {...props}
  />
))
SelectSeparator.displayName = SelectPrimitive.Separator.displayName

export {
  Select,
  SelectGroup,
  SelectValue,
  SelectTrigger,
  SelectContent,
  SelectLabel,
  SelectItem,
  SelectSeparator,
  SelectScrollUpButton,
  SelectScrollDownButton,
}
