"use client"

import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import * as TooltipPrimitive from "@radix-ui/react-tooltip"

import { listenKeys } from "@/lib/shortcuts"
import { cn } from "@/lib/utils"

import { APP_CHROME } from "./appChrome"
import { FLOATING_COLLISION_PADDING } from "./floating"
import { useFloatMirror } from "./floatLayer"
import { Kbd, KbdGroup } from "./kbd"
import { HintRegion, HintScope, ProviderMark, type HintRegionValue, type ScopedText, type ScopeRegister, type Side } from "./tooltipContext"


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

/** 说明浮层的外观。长网址、长文件名在浮层里折行(任意处可断),不把浮层撑出窗口。 */
const TOOLTIP_SURFACE =
  "z-50 max-w-[min(20rem,calc(100vw-1rem))] overflow-hidden rounded-md border border-border bg-popover px-3 py-1.5 text-xs leading-relaxed text-popover-foreground [overflow-wrap:anywhere]"
const TOOLTIP_MOTION =
  "animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 origin-(--radix-tooltip-content-transform-origin) motion-reduce:animate-none"

/**
 * 说明浮层。在内嵌浏览器外壳(`HintRegion`)里时交给浮层视图画到原生网页视图上面(见 useFloatMirror),
 * DOM 里这份只留着量位置、给读屏。
 */
const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 4, ...props }, ref) => {
  //: 浮层内容只在打开时才挂上(Radix 的 Presence),所以用 state 记住它 —— 挂上那一刻才开始交给浮层视图。
  const [node, setNode] = React.useState<HTMLDivElement | null>(null)
  useFloatMirror(node, mirrorsToFloat(React.useContext(HintRegion)))
  const setRef = React.useCallback(
    (element: HTMLDivElement | null) => {
      setNode(element)
      if (typeof ref === "function") ref(element)
      else if (ref) ref.current = element
    },
    [ref],
  )
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        ref={setRef}
        data-tooltip=""
        sideOffset={sideOffset}
        collisionPadding={FLOATING_COLLISION_PADDING}
        className={cn(TOOLTIP_SURFACE, TOOLTIP_MOTION, className)}
        {...props}
      />
    </TooltipPrimitive.Portal>
  )
})
TooltipContent.displayName = TooltipPrimitive.Content.displayName

/**
 * 焦点是不是**键盘在控件之间挪过来的**(Tab、方向键、Home / End)。说明因聚焦而出只认这一种。
 *
 * 焦点还会被程序挪:关掉菜单、面板、对话框时 Radix 把焦点还给打开它的那枚按钮。让这一下出说明的话,
 * 关掉一个菜单,那枚按钮上就冒出一条说明,鼠标移到别处也不走。所以按下挪焦点的键记一笔,**按别的键就清掉**
 * —— Esc、Enter、空格正是关菜单、选中、确认的那几下:在菜单里用方向键挑完再按 Esc / Enter,焦点还回去的
 * 那一下不算键盘切过来的(此前只有指针能清,方向键挑过菜单的人一关菜单就看到说明冒出来)。指针一动也清。
 */
const NAVIGATION_KEYS = new Set(["Tab", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"])
let keyboardNavigation = false
if (typeof document !== "undefined") {
  listenKeys(document, (event) => {
    keyboardNavigation = NAVIGATION_KEYS.has(event.key)
  }, true)
  const pointer = () => {
    keyboardNavigation = false
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


/** 快捷键:一个字符串是一颗键帽(`⌘Z`、`⇧⌘Z`);数组是几个键任选其一(`⇧⌘Z / ⌘Y`)。 */
export type HintShortcut = string | readonly string[]


/** 并进 Hint 说明里的一段:被截断的全文(正文色),或 Truncate 补充的那一句(跟在全文后面时淡一档)。 */
type ScopedLine = { text: React.ReactNode; kind: "full" | "hint"; muted: boolean }

/** 打开的那一刻量一次:哪几段字真被截断了、各自补充哪一句。和 Hint 自己那两句重复的不再说一遍。 */
function scopedLines(texts: Iterable<ScopedText>, own: (string | null | undefined)[]): ScopedLine[] {
  const fresh = (one: React.ReactNode | null) => one !== null && one !== undefined && one !== "" && !own.includes(one as string)
  return [...texts].flatMap((get) => {
    const { full, hint } = get()
    const lines: ScopedLine[] = fresh(full) ? [{ text: full, kind: "full", muted: false }] : []
    if (fresh(hint)) lines.push({ text: hint, kind: "hint", muted: lines.length > 0 })
    return lines
  })
}


/** 区域里的说明怎么摆:默认方向听区域的(放不下 Radix 会翻到对面)。 */
function regionPlacement(region: HintRegionValue | null, side: Side | undefined) {
  if (!region) return { side: side ?? "top" }
  const placed = side ?? region.side ?? "top"
  return region.layer === "lightbox" ? { side: placed, "data-over-lightbox": "" } : { side: placed, "data-over-chrome": "" }
}

/** 这块里的说明要交给浮层视图画到原生网页视图上面吗(外壳里要;大图那一层不用 —— 视图已经让开了)。 */
const mirrorsToFloat = (region: HintRegionValue | null) => region !== null && region.layer !== "lightbox"

const CHROME_LAYER = { ...APP_CHROME, "data-over-chrome": "" } as const

/**
 * 外壳(区域)里打开的浮层 —— Popover、Select、右键菜单 —— 也是外壳:portal 到 body 上,却是从外壳里开出来的。
 * - 标 `data-over-chrome`:层抬到外壳之上。不抬就是 z 120,压在 z 200 的那一列底下,点了像没反应(工作台模型库的小眼睛);
 * - 挂 `APP_CHROME`:底下开着模态弹窗(工作流库)时,焦点进浮层不被弹窗的焦点圈套拽回去 —— 拽回去,浮层当成焦点跑到外面、
 *   当场关掉;在里面点、按 Esc 不关底下的弹窗;内嵌网页亮着时里面的按键不被当成落在看不见的地方吞掉(embeddedFocus)。
 * 不在区域里时什么都不加。
 */
function useChromeLayer() {
  return React.useContext(HintRegion) ? CHROME_LAYER : undefined
}

/** 浮层内容用它把 Hint 的范围清掉(见 HintScope)。 */
function HintScopeReset({ children }: { children?: React.ReactNode }) {
  return <HintScope.Provider value={null}>{children}</HintScope.Provider>
}

/** 不收登记的范围:直接用 Tooltip 的富内容卡片里被截断的字,不另出一条(见 HintScope)。 */
const IGNORE_SCOPED: ScopeRegister = () => () => {}

/** 每一下指针移动 / 聚焦只开一条说明:里层的触发器收下了,外层就不再拿它去开自己那条(见 TooltipTrigger)。 */
const claimed = new WeakSet<Event>()

/**
 * 夹在 Radix 的触发器和真正那个元素之间的一道闸:「指针进来了」「聚焦了」只在这条说明**该出**的时候才交给 Radix。
 *
 * 不能等 Radix 问过之后再在 onOpenChange 里拒绝:Radix 一试图打开,先广播 `tooltip.open` 把别的说明全关掉、
 * 再让下一条免等待,然后才问我们 —— 拒绝了也晚了,开着的那条已经被关掉。也不能在事件上 preventDefault
 * 让 Radix 跳过:同一个事件还要冒泡给外层的触发器和别的组件(工具条的方向键焦点就听 onFocus)。
 * 闸只拦它自己身后那一个 Radix 触发器,事件照常往上走。
 */
const OpenGate = React.forwardRef<HTMLElement, React.HTMLAttributes<HTMLElement> & { canOpen?: () => boolean }>(
  function OpenGate({ canOpen, onPointerMove, onFocus, ...forwarded }, ref) {
    //: Radix 往触发器上写自己的 `data-state`(closed / delayed-open / instant-open)。asChild 时它落在**控件本身**上,
    //: 盖掉控件自己的那一个 —— Switch 的 checked / unchecked、Checkbox、Toggle 的样式都按它画,于是浏览器池卡片上的
    //: 启用开关只剩一个看不见状态的淡点(体检 UM-05)。没有哪里按说明的开合来画触发器,这一个就不往下交了;
    //: 「这是一条说明的触发器」改由 `data-hint-trigger` 标出来。
    const { "data-state": _hintState, ...props } = forwarded as typeof forwarded & { "data-state"?: string };
    const admit = (event: React.SyntheticEvent<HTMLElement>, wanted: boolean) => {
      if (!wanted || claimed.has(event.nativeEvent)) return false
      //: 事件目标不在这块元素里:它是从 portal 里(这个控件自己弹出来的下拉、菜单)顺着 React 的树冒上来的
      if (!event.currentTarget.contains(event.target as Node)) return false
      if (canOpen && !canOpen()) return false
      claimed.add(event.nativeEvent)
      return true
    }
    return (
      <Slot
        ref={ref}
        {...props}
        data-hint-trigger=""
        onPointerMove={(event: React.PointerEvent<HTMLElement>) => {
          if (admit(event, event.pointerType !== "touch")) onPointerMove?.(event)
        }}
        onFocus={(event: React.FocusEvent<HTMLElement>) => {
          if (admit(event, keyboardNavigation)) onFocus?.(event)
        }}
      />
    )
  },
)

/**
 * 说明的触发器 —— Hint、Truncate 和直接用 Tooltip 的富内容卡片都经过它。**「这一下该不该出说明」只在这里判**:
 *
 * 1. **指针真的在这块元素上。** React 的事件顺着组件树冒泡,穿过 portal:一个套在 Hint 里的下拉(Hint 包着
 *    整个选择器,弹出来的清单是它的子组件),在清单里移动指针、用方向键挑选项,这些事件都会冒到 Hint 的触发器上
 *    —— 说明就在下拉开着的时候挂到触发器上,盖在清单上,每挪一次焦点开一次关一次(画板「4×」那一格的闪烁)。
 *    所以只认目标在这块元素的 DOM 里面的事件。
 * 2. **聚焦只认键盘切过来的**(见 keyboardNavigation):焦点被还回来、被程序放过来都不出。
 * 3. **有话可说才去开**(`canOpen`):没名字、没被截断的字时一声不响。
 * 4. **一处只出一条,里层的说了算。** 两个触发器叠在一起(外层一条 Hint 包着一个自带说明的控件),一下指针移动
 *    只开最里面那条有话可说的;外层只在指针落在里层够不着的地方时出。和原生 `title` 一样:离指针最近的那条。
 *    自己没话说的那层不认领,也不另开一条(见 Hint)。
 *
 * `scope`:这块里被截断的字(Truncate)交给谁(见 HintScope)。缺省不收 —— 直接用 Tooltip 的卡片就是这块的说明。
 */
const TooltipTrigger = React.forwardRef<
  HTMLButtonElement,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Trigger> & { canOpen?: () => boolean; scope?: ScopeRegister }
>(function TooltipTrigger({ asChild, canOpen, scope = IGNORE_SCOPED, children, ...props }, ref) {
  return (
    // Provider 套在 Trigger 外面:asChild 的 Slot 只能把属性交给一个真正的元素。
    <HintScope.Provider value={scope}>
      <TooltipPrimitive.Trigger asChild ref={ref} {...props}>
        <OpenGate canOpen={canOpen}>{asChild ? children : <button type="button">{children}</button>}</OpenGate>
      </TooltipPrimitive.Trigger>
    </HintScope.Provider>
  )
})

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
 * **只在指针真的停在上面、或键盘切过来时出**,同一时刻只有一条(closeOpenHint)。什么时候算,见 TooltipTrigger。
 *
 * 没有可说的(`label`、`disabledReason` 都是空)就不出说明,但结构照旧 —— 「有时有说明」的控件
 * (`label={problem ?? undefined}`)不会因为说明来去而被换掉一层、丢了焦点。这时它若套在另一条说明的触发区里
 * (外层一条 Hint 包着整个选择器,选择器自己的触发器也套着 Hint),就**让外面那条替整块说**:不认领指针和焦点,
 * 里面被截断的字(触发器里的值)也交给外面那条,并进同一条说明。
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
  const outer = React.useContext(HintScope)
  const scoped = React.useRef(new Set<ScopedText>())
  const register = React.useCallback((get: ScopedText) => {
    scoped.current.add(get)
    return () => {
      scoped.current.delete(get)
    }
  }, [])
  const [lines, setLines] = React.useState<ScopedLine[]>([])
  const speaks = Boolean(label || disabledReason)
  const measure = () => scopedLines(scoped.current, [label, hint])
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
          const measured = measure()
          if (!speaks && measured.length === 0) return
          setLines(measured)
          setOpen(true)
        }}
      >
        <TooltipTrigger
          asChild
          //: 自己没话说又在别的说明里:范围原样往里传,里面被截断的字交给外面那条(见上面的注释)
          scope={!speaks && outer ? outer : register}
          canOpen={() => speaks || measure().length > 0}
          onPointerLeave={() => setOpen(false)}
        >
          {trigger}
        </TooltipTrigger>
        <TooltipContent {...placement} align={align} data-hint="">
          {lines.map((line, index) => (
            <span key={index} data-truncate-line={line.kind} className={cn("block whitespace-pre-wrap", line.muted && "text-muted-foreground")}>
              {line.text}
            </span>
          ))}
          {label ? (
            <span className={cn("flex items-center justify-between gap-3", lines.length > 0 && "text-muted-foreground")}>
              {/* 换行照写的来(画板格子「详情」里的「原因 + 怎么修」一步一行);没有换行的说明不受影响 */}
              <span className="whitespace-pre-line">{label}</span>
              {shortcut && shortcut.length > 0 ? <Shortcut keys={shortcut} /> : null}
            </span>
          ) : null}
          {hint && hint !== label ? <span className="block whitespace-pre-line text-muted-foreground">{hint}</span> : null}
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
  useChromeLayer,
  EnsureProvider,
  useExclusiveOpen,
  HintScope,
  HintScopeReset,
}
