"use client"

import * as React from "react"
import * as TooltipPrimitive from "@radix-ui/react-tooltip"

import { listenKeys } from "@/lib/shortcuts"
import { cn } from "@/lib/utils"

import { FLOATING_COLLISION_PADDING } from "./floating"
import { Kbd, KbdGroup } from "./kbd"

/**
 * 应用根上的 Provider 顺手挂一个标记。Hint / Truncate 在没有 Provider 的地方(单独渲染一个组件的
 * 测试、孤立挂载的浮层)自己补一个,而不是像 Radix 那样抛错 —— 抛错的话,每个用到图标按钮的
 * 组件测试都得先包一层 Provider,漏一层就是一条与被测功能无关的红。
 *
 * 只是兜底:补出来的那个 Provider 只管它自己,一排按钮之间「移过去立刻出」(skipDelayDuration)
 * 要靠外面那个共同的 Provider。应用里永远有(App.tsx)。
 */
const ProviderMark = React.createContext(false)

function TooltipProvider({ children, ...props }: React.ComponentProps<typeof TooltipPrimitive.Provider>) {
  return (
    <TooltipPrimitive.Provider {...props}>
      <ProviderMark.Provider value>{children}</ProviderMark.Provider>
    </TooltipPrimitive.Provider>
  )
}

function EnsureProvider({ children }: { children: React.ReactNode }) {
  if (React.useContext(ProviderMark)) return <>{children}</>
  return <TooltipProvider delayDuration={300}>{children}</TooltipProvider>
}

const Tooltip = TooltipPrimitive.Root

const TooltipTrigger = TooltipPrimitive.Trigger

/** 说明浮层的外观。长网址、长文件名在浮层里折行(任意处可断),不把浮层撑出窗口。 */
const TOOLTIP_SURFACE =
  "z-50 max-w-[min(20rem,calc(100vw-1rem))] overflow-hidden rounded-md border border-border bg-popover px-3 py-1.5 text-xs leading-relaxed text-popover-foreground [overflow-wrap:anywhere]"
const TOOLTIP_MOTION =
  "animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 origin-(--radix-tooltip-content-transform-origin) motion-reduce:animate-none"

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
      className={cn(TOOLTIP_SURFACE, TOOLTIP_MOTION, className)}
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

/** 同一时刻只留一条说明:新的一条出来时,上一条收起(Hint 和 Truncate 共用这一个名额)。 */
let closeOpenHint: (() => void) | null = null

function useExclusiveOpen(): [boolean, (next: boolean) => void] {
  const [open, setOpen] = React.useState(false)
  const close = React.useCallback(() => setOpen(false), [])
  React.useEffect(() => {
    if (!open) return
    if (closeOpenHint && closeOpenHint !== close) closeOpenHint()
    closeOpenHint = close
    return () => {
      if (closeOpenHint === close) closeOpenHint = null
    }
  }, [open, close])
  return [open, setOpen]
}

type Side = "top" | "bottom" | "left" | "right"

/** 快捷键:一个字符串是一颗键帽(`⌘Z`、`⇧⌘Z`);数组是几个键任选其一(`⇧⌘Z / ⌘Y`)。 */
export type HintShortcut = string | readonly string[]

/**
 * Hint 的触发区里有会被截断的字(Truncate)时,**说明只出一条**:那段字被截断了,就把全文并进
 * 这条说明里,而不是在同一处再挂一个说明 —— 两条说明叠在同一块上,同一时刻只留一条的规则会让
 * 其中一条永远出不来(要么看不到全文,要么看不到补充说明)。
 *
 * Truncate 在这个范围里就不自己出说明,只登记「我现在被截断了吗、全文是什么」。浮层内容
 * (Popover / Select / ContextMenu / Dialog 的 Content)会把范围清掉:React 的 context 会穿过
 * portal,不清的话,一个套在 Hint 里的组件弹出来的菜单项也会把全文交给外面那条够不着它的说明。
 */
type OverflowText = () => React.ReactNode | null
const HintScope = React.createContext<((get: OverflowText) => () => void) | null>(null)

/**
 * 说明浮层所在的「区域」,给**内嵌浏览器**那几块用:顶栏、侧栏。它们压在原生网页视图周围,z 是 200,比所有
 * 浮层(styles.css 统一定成 120)都高 —— 不说一声,说明就画在它们底下。
 *
 * - `band`:只能画在这一条横带里(顶栏)。顶栏下面是原生网页视图,盖在一切 DOM 上 —— 说明往下出被它盖住,
 *   往上出又出了窗口(窗口装饰那一截的避让也会把它推下去)。带里的说明默认往左右出,竖直方向夹在带里;
 *   两行(名字 + 一句说明)放得下 56px 的顶栏。
 * - `band: null`:不限位置,只是要压在这块上面(侧栏:它旁边的网页让开了,浮层照常摆)。
 *
 * 两种都给浮层标上 `data-over-chrome`,styles.css 据此把它那层抬到顶栏、侧栏之上。
 */
const HintRegion = React.createContext<{ band: { top: number; height: number } | null } | null>(null)

/** 区域里的说明怎么摆:带里默认往左出(放不下 Radix 会翻到右边),上下的避让按带的上下沿算。 */
function regionPlacement(region: { band: { top: number; height: number } | null } | null, side: Side | undefined) {
  if (!region) return { side: side ?? "top" }
  const band = region.band
  if (!band) return { side: side ?? "top", "data-over-chrome": "" }
  const viewport = typeof window === "undefined" ? band.top + band.height : window.innerHeight
  return {
    side: side ?? "left",
    collisionPadding: { top: band.top, bottom: Math.max(0, viewport - band.top - band.height), left: 8, right: 8 },
    "data-over-chrome": "",
  }
}

/** 浮层内容用它把 Hint 的范围清掉(见 HintScope)。 */
function HintScopeReset({ children }: { children?: React.ReactNode }) {
  return <HintScope.Provider value={null}>{children}</HintScope.Provider>
}

function Shortcut({ keys }: { keys: HintShortcut }) {
  return typeof keys === "string" ? <Kbd>{keys}</Kbd> : <KbdGroup keys={keys} />
}

/**
 * 一个控件的悬停说明:名字一行(有快捷键就用键帽画在同一行右边),补充的一句淡色在下面,
 * 点不了时再一行淡色写为什么。
 *
 * 图标按钮只有图形,**名字得在悬停时马上出来**(Provider 的 delayDuration,应用里是 300ms)——
 * 原生 `title` 要停一秒多、样式是系统的、深色下也不跟主题,在一排图标上等于没有。读屏的名字仍然是
 * 按钮自己的 `aria-label`,这里只管看得见的那一份。只有图标的按钮别直接套这个,用 `IconButton`:
 * 名字只写一次,两份都给。
 *
 * **只在指针真的停在上面、或键盘切过来时出**(见 keyboardInput),同一时刻只有一条(closeOpenHint)。
 *
 * 没有可说的(`label`、`disabledReason` 都是空)就不出说明,但结构照旧 —— 「有时有说明」的控件
 * (`label={problem ?? undefined}`)不会因为说明来去而被换掉一层、丢了焦点。
 *
 * `disabledReason`:**点不了的按钮自己收不到悬停**(disabled 的原生按钮不派发指针事件,Button
 * 还挂着 `disabled:pointer-events-none`)。给了原因就在外面套一层能接住指针和键盘焦点的壳
 * (`data-hint-disabled`),说明挂在壳上;不给就不套,能点的按钮结构不变。所以调用方只在真点不了
 * 的时候给:`disabledReason={busy ? t("…") : undefined}` —— IconButton 已经替你按 `disabled` 判了。
 */
function Hint({
  label,
  hint,
  shortcut,
  disabledReason,
  side,
  align,
  children,
}: {
  /** 第一行:控件叫什么,或者(文字按钮上)那句补充说明。文字已经写清楚的按钮别再套一层说一遍。 */
  label?: string | null
  hint?: string | null
  shortcut?: HintShortcut | null
  disabledReason?: string | false | null
  side?: Side
  align?: "start" | "center" | "end"
  children: React.ReactNode
}) {
  const [open, setOpen] = useExclusiveOpen()
  const placement = regionPlacement(React.useContext(HintRegion), side)
  const hovered = React.useRef(false)
  const overflows = React.useRef(new Set<OverflowText>())
  const register = React.useCallback((get: OverflowText) => {
    overflows.current.add(get)
    return () => {
      overflows.current.delete(get)
    }
  }, [])
  //: 打开的那一刻量一次:哪几段字真被截断了(和名字重复的不再说一遍)。
  const [full, setFull] = React.useState<React.ReactNode[]>([])
  const measure = () => [...overflows.current].map((get) => get()).filter((one) => one !== null && one !== undefined && one !== "" && one !== label)
  const trigger = disabledReason ? (
    <span
      data-hint-disabled=""
      tabIndex={0}
      className="inline-flex max-w-full cursor-not-allowed rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring [&>*]:pointer-events-none"
    >
      {children}
    </span>
  ) : (
    children
  )
  return (
    <EnsureProvider>
      <Tooltip
        open={open}
        onOpenChange={(next) => {
          if (!next) {
            setOpen(false)
            return
          }
          if (!hovered.current && !keyboardInput) return
          const clipped = measure()
          if (!label && !disabledReason && clipped.length === 0) return
          setFull(clipped)
          setOpen(true)
        }}
      >
        {/* Provider 套在 Trigger 外面:asChild 的 Slot 只能把属性交给一个真正的元素。 */}
        <HintScope.Provider value={register}>
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
            {trigger}
          </TooltipTrigger>
        </HintScope.Provider>
        <TooltipContent {...placement} align={align} data-hint="">
          {full.map((one, index) => (
            <span key={index} data-truncate-full="" className="block whitespace-pre-wrap">
              {one}
            </span>
          ))}
          {label ? (
            <span className={cn("flex items-center justify-between gap-3", full.length > 0 && "text-muted-foreground")}>
              <span>{label}</span>
              {shortcut && shortcut.length > 0 ? <Shortcut keys={shortcut} /> : null}
            </span>
          ) : null}
          {hint && hint !== label ? <span className="block text-muted-foreground">{hint}</span> : null}
          {disabledReason ? <span className={cn("block", label && "text-muted-foreground")}>{disabledReason}</span> : null}
        </TooltipContent>
      </Tooltip>
    </EnsureProvider>
  )
}

export {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
  Hint,
  HintRegion,
  regionPlacement,
  EnsureProvider,
  useExclusiveOpen,
  HintScope,
  HintScopeReset,
}
