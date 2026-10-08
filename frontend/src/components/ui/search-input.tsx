import * as React from "react"
import { Search } from "lucide-react"

import { type FieldSize, SEARCH_FIELD } from "@/components/ui/control-size"
import { Input, type InputProps } from "@/components/ui/input"
import { cn } from "@/lib/utils"

/**
 * 搜索框:字段的样子(和输入框、下拉同一种描边、底色、档位),左边一个放大镜。右头可以放一小段东西(`trailing`:
 * 结果数「3 / 12」、键帽),输入框给它让出位置。
 *
 * 此前十几处各自拼:一个 `relative` 的外壳、一个绝对定位的 `<Search>`、一个 `pl-8` / `pl-9` / `pl-[30px]` 的输入框 ——
 * 放大镜大小、离左边多远、输入框让多少各不相同;列表页的两处还另换了底色和描边。`className` 给外壳(宽度、伸缩),
 * 不改高度、留白、字号。ref 指向里面的输入框。
 */
export const SearchInput = React.forwardRef<
  HTMLInputElement,
  Omit<InputProps, "className"> & {
    /** 外壳的排版(宽度、flex)。 */
    className?: string
    /** 右头的一小段(结果数、键帽)。 */
    trailing?: React.ReactNode
    /** 右头那一段要多宽(给输入框让多少),默认 3rem。 */
    trailingWidth?: "sm" | "md" | "lg"
  }
>(({ className, size = "md", trailing, trailingWidth = "md", ...props }, ref) => {
  const tier = SEARCH_FIELD[size as FieldSize]
  return (
    <div data-search-input="" className={cn("relative min-w-0", className)}>
      <Search aria-hidden className={cn("pointer-events-none absolute top-1/2 -translate-y-1/2 text-muted-foreground", tier.icon)} />
      <Input
        ref={ref}
        size={size}
        className={cn(tier.pad, trailing ? { sm: "pr-10", md: "pr-12", lg: "pr-16" }[trailingWidth] : undefined)}
        {...props}
      />
      {trailing && (
        <span className={cn("pointer-events-none absolute top-1/2 flex -translate-y-1/2 items-center text-ui-xs tabular-nums text-muted-foreground", tier.trailing)}>
          {trailing}
        </span>
      )}
    </div>
  )
})
SearchInput.displayName = "SearchInput"
