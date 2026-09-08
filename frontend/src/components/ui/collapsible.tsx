import * as React from "react"
import * as CollapsiblePrimitive from "@radix-ui/react-collapsible"

import { cn } from "@/lib/utils"

/**
 * 可折叠区块。
 *
 * **换掉原生 `<details>`。** 后者的三角形由浏览器画,大小、颜色、间距都不归我们管 ——
 * 在这个应用的深色面板里它是一个突兀的实心小三角,和旁边所有图标的粗细都对不上;而且
 * 开合没有过渡,内容是"啪"地出现的。Radix 这个给的是普通元素,图标和动画都由我们决定。
 */
const Collapsible = CollapsiblePrimitive.Root

const CollapsibleTrigger = CollapsiblePrimitive.CollapsibleTrigger

const CollapsibleContent = React.forwardRef<
  React.ElementRef<typeof CollapsiblePrimitive.CollapsibleContent>,
  React.ComponentPropsWithoutRef<typeof CollapsiblePrimitive.CollapsibleContent>
>(({ className, ...props }, ref) => (
  <CollapsiblePrimitive.CollapsibleContent
    ref={ref}
    // Radix 量好高度写进 --radix-collapsible-content-height,动画照着它走。
    className={cn(
      "overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down motion-reduce:animate-none",
      className,
    )}
    {...props}
  />
))
CollapsibleContent.displayName = CollapsiblePrimitive.CollapsibleContent.displayName

export { Collapsible, CollapsibleTrigger, CollapsibleContent }
