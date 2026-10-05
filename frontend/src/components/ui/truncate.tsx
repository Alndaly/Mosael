import * as React from "react"

import { cn } from "@/lib/utils"

import { EnsureProvider, HintRegion, HintScope, Tooltip, TooltipContent, TooltipTrigger, regionPlacement, useExclusiveOpen } from "./tooltip"

const CLAMP = { 1: "truncate", 2: "line-clamp-2", 3: "line-clamp-3", 4: "line-clamp-4" } as const

/** 截断的字可以是哪种元素。标题、段落、代码这些语义要留着,不能为了截断一律变成 span。 */
type TruncateTag = "span" | "p" | "div" | "small" | "strong" | "em" | "code" | "h2" | "h3" | "h4" | "figcaption" | "dt" | "dd" | "li" | "blockquote" | "label"

/**
 * 会被截断的一段字:放不下时省略号收尾,**真被截断了**悬停才出说明,说明里是全文。
 *
 * 用在名字、文件名、网址、工作流名、模型名、用户输入这类**长度不由我们定**的值上 —— 列表行、
 * 卡片标题、菜单里的动态项、下拉触发器里选中的值。它们不该把容器撑开,也不该截了就再也看不全。
 * 原生 `title` 做过这件事,但它不管放不放得下都出(短名字悬停再念一遍是噪音)、要停一秒多、
 * 样式是系统的。
 *
 * 全文一直在 DOM 里,读屏念的是全文;说明只是给眼睛看的那一份。显示的不是纯文字(带高亮、
 * 带标记)时用 `text` 给说明里的全文。
 *
 * 默认 `block min-w-0`:截断要一个有宽度的盒子,而 flex / grid 里的子项不归零 min-width 就
 * 不肯收缩(见 field-trigger.ts)。要行内排版的地方用 className 改。
 */
const Truncate = React.forwardRef<
  HTMLElement,
  Omit<React.HTMLAttributes<HTMLElement>, "title"> & {
    children: React.ReactNode
    /** 说明里的全文。不给就用 children。 */
    text?: React.ReactNode
    /**
     * 名字之外要补一句的(完整地址、模型 id、「双击改名」):说明里全文下面一行淡色。给了它,
     * 没被截断时也出说明(只有这一句)。别在外面再套 Hint 说这一句 —— 那就是同一处挂两条说明。
     * 已经在一条 Hint 的触发区里时,这一句并进那条 Hint 的说明(见 tooltip.tsx 的 HintScope)。
     */
    hint?: string | null
    /** 截成几行。默认一行(省略号);多行用于卡片描述这类本来就该折几行的字。 */
    lines?: keyof typeof CLAMP
    side?: "top" | "bottom" | "left" | "right"
    /** 渲染成哪种元素,默认 span。 */
    as?: TruncateTag
    /** 给 `<label>` 用。 */
    htmlFor?: string
  }
>(({ children, text, hint, lines = 1, side, as: Tag = "span", className, onPointerEnter, onPointerLeave, ...props }, forwarded) => {
  const [open, setOpen] = useExclusiveOpen()
  const region = React.useContext(HintRegion)
  const [clipped, setClipped] = React.useState(false)
  const ref = React.useRef<HTMLElement | null>(null)
  const setRef = React.useCallback(
    (node: HTMLElement | null) => {
      ref.current = node
      if (typeof forwarded === "function") forwarded(node)
      else if (forwarded) forwarded.current = node
    },
    [forwarded],
  )
  const overflowing = () => {
    const node = ref.current
    if (!node) return false
    return lines === 1 ? node.scrollWidth > node.clientWidth + 1 : node.scrollHeight > node.clientHeight + 1
  }
  //: 在一条 Hint 的触发区里:不自己出说明,把「被截断时的全文」和补充的那句交给那条(见 tooltip.tsx 的 HintScope)。
  const scope = React.useContext(HintScope)
  const full = text ?? children
  const scoped = () => ({ full: overflowing() ? full : null, hint: hint ?? null })
  const latest = React.useRef(scoped)
  latest.current = scoped
  React.useEffect(() => scope?.(() => latest.current()), [scope])
  const element = (
    <Tag
      ref={setRef as React.Ref<never>}
      className={cn("block min-w-0", CLAMP[lines], lines > 1 && "break-words", className)}
      onPointerEnter={onPointerEnter}
      onPointerLeave={(event: React.PointerEvent<HTMLElement>) => {
        onPointerLeave?.(event)
        if (!scope) setOpen(false)
      }}
      {...props}
    >
      {children}
    </Tag>
  )
  if (scope) return element
  return (
    <EnsureProvider>
      <Tooltip
        open={open}
        onOpenChange={(next) => {
          // **收起时不动内容**:浮层还要淡出一下(TOOLTIP_MOTION),此前这里把 clipped 清成 false,淡出的那几帧里
          // 全文先没了,画出来一个空的小气泡。下拉列表里鼠标往下划过一排被截断的名字,每一行都留下一个正在淡出的
          // 空气泡 —— 看上去就是提示闪了好几下。是不是被截断,只在打开那一刻量。
          if (!next) {
            setOpen(false)
            return
          }
          const cut = overflowing()
          setClipped(cut)
          setOpen(cut || Boolean(hint))
        }}
      >
        <TooltipTrigger asChild>{element}</TooltipTrigger>
        <TooltipContent {...regionPlacement(region, side)} data-truncate-full="" className="max-w-[min(28rem,calc(100vw-1rem))] whitespace-pre-wrap">
          {clipped ? <span className="block">{full}</span> : null}
          {hint ? <span className={cn("block", clipped && "text-muted-foreground")}>{hint}</span> : null}
        </TooltipContent>
      </Tooltip>
    </EnsureProvider>
  )
})
Truncate.displayName = "Truncate"

export { Truncate }
