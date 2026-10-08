"use client"

import * as React from "react"
import * as TabsPrimitive from "@radix-ui/react-tabs"

import { CONTROL_HEIGHT } from "@/components/ui/control-size"
import { cn } from "@/lib/utils"

/**
 * 页签的一项:14px 中等字重、次要色,选中的那一项强调色字 + 2px 底线;悬停回到前景色。
 * **两种写法同一个样子**:内容区一整条的(这里的 TabsList / TabsTrigger,44px、下面一条分隔线),和列表页筛选条里那一排
 * (components/layout/StudioPage 的 CollectionTabs,随那一行 40px、不画分隔线)。选中态用哪个属性表达各走各的
 * (Radix 是 data-state,CollectionTabs 是 aria-selected),所以这里两个都认。
 */
export const TAB_TRIGGER =
  "inline-flex shrink-0 cursor-pointer items-center justify-center gap-2 whitespace-nowrap border-b-2 border-transparent px-1 text-ui-sm font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset disabled:pointer-events-none disabled:opacity-50 data-[state=active]:border-primary data-[state=active]:text-primary aria-selected:border-primary aria-selected:text-primary"

const Tabs = TabsPrimitive.Root

const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(
      cn("inline-flex items-stretch justify-start gap-5 border-b border-divider", CONTROL_HEIGHT.lg),
      className
    )}
    {...props}
  />
))
TabsList.displayName = TabsPrimitive.List.displayName

const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(TAB_TRIGGER, className)}
    {...props}
  />
))
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName

const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      "mt-2 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
      className
    )}
    {...props}
  />
))
TabsContent.displayName = TabsPrimitive.Content.displayName

export { Tabs, TabsList, TabsTrigger, TabsContent }
