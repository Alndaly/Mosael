"use client"

import * as React from "react"
import * as SelectPrimitive from "@radix-ui/react-select"
import { Check, ChevronDown, ChevronUp } from "lucide-react"

import type { FieldSize } from "@/components/ui/control-size"
import { fieldTriggerClass, FIELD_TRIGGER_CHEVRON } from "@/components/ui/field-trigger"
import { FLOATING_SURFACE, FLOATING_MOTION, MENU_SEPARATOR, FLOATING_COLLISION_PADDING, SELECT_CONTENT_WIDTH } from "./floating"
import { Truncate } from "./truncate"
import { HintScopeReset } from "./tooltip"

import { cn } from "@/lib/utils"
import { swallowClickThrough } from "@/lib/clickThrough"

const Select = SelectPrimitive.Root

const SelectGroup = SelectPrimitive.Group

const SelectValue = SelectPrimitive.Value

const SelectTrigger = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger> & {
    /** 档位,和 `<Input size>`、`<Button size>` 同一把尺。见 control-size.ts 的 FIELD_SIZE。 */
    size?: FieldSize
  }
>(({ className, children, size, ...props }, ref) => (
  <SelectPrimitive.Trigger
    ref={ref}
    className={cn(fieldTriggerClass(size), className)}
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
        // 上限也不能没有:没有上限时一个 checkpoint 文件名就把菜单撑满整个窗口。规则见 SELECT_CONTENT_WIDTH。
        position === "popper" && SELECT_CONTENT_WIDTH,
        position === "popper" &&
          "data-[side=bottom]:translate-y-1.5 data-[side=left]:-translate-x-1.5 data-[side=right]:translate-x-1.5 data-[side=top]:-translate-y-1.5",
        className
      )}
      position={position}
      collisionPadding={FLOATING_COLLISION_PADDING}
      {...props}
      //: 鼠标抬起就选中、菜单随即关掉,补发的 click 会落到菜单下面的东西上(画板上那格视频开始播放):吞掉那一下。
      onPointerUp={(event) => {
        props.onPointerUp?.(event)
        swallowClickThrough(event, (target) => target instanceof Element && Boolean(target.closest("[data-radix-select-viewport]")))
      }}
    >
      <SelectScrollUpButton />
      <SelectPrimitive.Viewport
        className={cn(
          "p-1.5",
          position === "popper" &&
            "h-[var(--radix-select-trigger-height)] w-full min-w-[var(--radix-select-trigger-width)]"
        )}
      >
        <HintScopeReset>{children}</HintScopeReset>
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
    /* **分组标题要一眼看出「这不是能点的那一行」。** 此前它和选项同字号、还更粗,唯一的区别
       是没有勾选位 —— 于是一列里粗一行细一行,读起来像两种选项而不是"一组的名字"。
       小一号 + 次要色 + 字距,是这套界面里"标签"一贯的样子(和设置页的分区标题同一档)。 */
    className={cn(
      "px-2 pb-1 pt-2.5 text-ui-2xs font-medium uppercase tracking-[0.04em] text-muted-foreground",
      className,
    )}
    {...props}
  />
))
SelectLabel.displayName = SelectPrimitive.Label.displayName

/**
 * 选项。`description` 是解释"选它会怎样"的副标题,静态文案,放不下就折行。
 *
 * **它必须待在 ItemText 外面。** Radix 把选中项的 ItemText **原样克隆进触发器** —— 副标题
 * 写进 children 的话,那一格就变成两行字,和旁边每一格都不一样高。副标题属于清单,
 * 不属于"当前选了什么"。
 *
 * 名字默认是静态文案:放不下就折行。**动态的长值**(模型名、文件名、音色名、服务端给的选项)
 * 传 `truncate`:单行截断、悬停看全文 —— 选中后克隆进触发器的也是这一份,触发器里被截断的值
 * 同样悬停看得到全文。
 */
const SelectItem = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item> & {
    description?: React.ReactNode
    truncate?: boolean
    /** 行首的一张小图(模型文件的缩略图)。在 ItemText 外面:选中后克隆进触发器的只有名字。 */
    media?: React.ReactNode
  }
>(({ className, children, description, truncate, media, ...props }, ref) => {
  const text = (
    <>
      {/* **类名写在外面这一层,不写在 ItemText 上**:Radix 的 ItemText 把 className、style 拆出来就扔了(源码里
          `const { className, style, ...itemTextProps } = props` 之后再没用过)。写在它上面的 `min-w-0` 从来没生效,
          名字那一格按整串文字的宽度排 —— 长文件名冲出菜单、不出省略号,Truncate 量不到截断,悬停也没有全文。 */}
      <span className="min-w-0 max-w-full break-words">
        <SelectPrimitive.ItemText>{truncate ? <Truncate>{children}</Truncate> : children}</SelectPrimitive.ItemText>
      </span>
      {description && <span className="min-w-0 break-words text-ui-xs leading-4 text-muted-foreground">{description}</span>}
    </>
  )
  return (
    <SelectPrimitive.Item
      ref={ref}
      className={cn(
        "relative flex min-h-9 w-full min-w-0 cursor-default select-none rounded-md py-2 pl-2.5 pr-8 text-ui-sm leading-5 outline-none focus:bg-secondary data-[disabled]:pointer-events-none data-[disabled]:opacity-40",
        media ? "items-center gap-2.5" : description ? "flex-col items-start gap-px" : "items-center",
        className
      )}
      {...props}
    >
      <span className="absolute right-2 top-2.5 flex h-3.5 w-3.5 items-center justify-center">
        <SelectPrimitive.ItemIndicator>
          <Check className="h-4 w-4" />
        </SelectPrimitive.ItemIndicator>
      </span>
      {media ? (
        <>
          <span aria-hidden className="grid size-9 shrink-0 overflow-hidden rounded-md [&>*]:size-full">{media}</span>
          <span className="grid min-w-0 flex-1 gap-px">{text}</span>
        </>
      ) : (
        text
      )}
    </SelectPrimitive.Item>
  )
})
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
