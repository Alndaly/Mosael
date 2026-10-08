import * as React from "react"

import { type ControlTier, SEGMENTED_SIZE } from "@/components/ui/control-size"
import { cn } from "@/lib/utils"

import { Hint } from "./tooltip"

/**
 * 分段控件:两到五个互斥选项、选项短、切换立刻生效(「对话 / 创作」「近 7 天 / 30 天」「网格 / 列表」)。
 * 选项要说明、要提交才生效、或超过五个 → 单选(radio-group)/ 下拉。规格见 docs/DESIGN_LANGUAGE.md「选择类控件」。
 *
 * **三档,总高度跟着这一行的档位**(control-size 的 SEGMENTED_SIZE):md 40(一项 32)、sm 32(一项 28)、xs 28(一项 24)。
 * 此前只有 40 这一档,别处在 className 里压成 36、32、28、24 等六种样子 —— 挑档,别压。
 *
 * 两种用法:
 * - `<Segmented>`:选项是数据,读屏和键盘(左右方向键换、Home / End 到头尾,换到哪个就选哪个)这里管;
 * - `segmentedListClass` / `segmentedItemClass`:每一项要自己渲染(页签要带 aria-controls、项里要放别的东西)时用这两串,
 *   语义(role、aria-checked / aria-selected、键盘)调用方自己给。
 */
export type SegmentedSize = ControlTier

const LIST = "inline-flex shrink-0 items-stretch bg-panel-subtle"
const ITEM =
  "inline-flex shrink-0 cursor-pointer items-center justify-center gap-1 whitespace-nowrap border-0 bg-transparent font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset disabled:pointer-events-none disabled:opacity-50"
const ACTIVE = "bg-accent text-accent-foreground hover:bg-accent hover:text-accent-foreground"

/** 外壳。`fill`:铺满这一行、每项等宽(对话框里那种一整行的分段)。 */
export function segmentedListClass(size: SegmentedSize = "md", { fill = false }: { fill?: boolean } = {}): string {
  return cn(LIST, SEGMENTED_SIZE[size].list, fill && "grid w-full auto-cols-fr grid-flow-col")
}

/** 里面一项。选中的那一项强调底色 + 强调色字,和按下的切换按钮同一种。 */
export function segmentedItemClass(active: boolean, size: SegmentedSize = "md"): string {
  return cn(ITEM, SEGMENTED_SIZE[size].item, active && ACTIVE)
}

const KEY_STEPS: Record<string, 1 | -1 | "first" | "last" | undefined> = {
  ArrowRight: 1,
  ArrowDown: 1,
  ArrowLeft: -1,
  ArrowUp: -1,
  Home: "first",
  End: "last",
}

export type SegmentedOption<T extends string> =
  | {
      value: T
      label: React.ReactNode
      /** 选项前面的图标(大小跟着档位)。 */
      icon?: React.ReactNode
      disabled?: boolean
      /** 名字放不下时给读屏的名字。 */
      ariaLabel?: string
    }
  | {
      value: T
      /** 只有图标的一项(网格 / 列表):名字给读屏,也是悬停说明。 */
      label?: undefined
      icon: React.ReactNode
      disabled?: boolean
      ariaLabel: string
    }

export function Segmented<T extends string>({
  value,
  onValueChange,
  options,
  size = "md",
  fill = false,
  "aria-label": ariaLabel,
  className,
  ...rest
}: {
  value: T
  onValueChange: (value: T) => void
  options: SegmentedOption<T>[]
  size?: SegmentedSize
  fill?: boolean
  "aria-label": string
  /** 只给排版用(外边距、对齐、宽度);高度、留白、圆角、字号由档位定。 */
  className?: string
} & Omit<React.HTMLAttributes<HTMLDivElement>, "onChange" | "role" | "aria-label" | "className">) {
  const refs = React.useRef<Array<HTMLButtonElement | null>>([])
  const enabled = options.map((option, index) => (option.disabled ? -1 : index)).filter((index) => index >= 0)
  //: 值不在清单里(还没归一化的那一帧)时,让第一个能选的那一项能被 Tab 到 —— 否则整排都是 -1,键盘进不来。
  const current = options.findIndex((option) => option.value === value)
  const focusable = current >= 0 && !options[current].disabled ? current : enabled[0] ?? -1
  const move = (from: number, step: 1 | -1 | "first" | "last") => {
    if (enabled.length === 0) return
    let next: number
    if (step === "first") next = enabled[0]
    else if (step === "last") next = enabled[enabled.length - 1]
    else {
      const at = enabled.indexOf(from)
      next = enabled[(at + step + enabled.length) % enabled.length]
    }
    onValueChange(options[next].value)
    refs.current[next]?.focus()
  }
  return (
    <div role="radiogroup" aria-label={ariaLabel} className={cn(segmentedListClass(size, { fill }), className)} {...rest}>
      {options.map((option, index) => {
        const active = option.value === value
        const iconOnly = option.label === undefined
        const item = (
          <button
            key={option.value}
            ref={(element) => {
              refs.current[index] = element
            }}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={option.ariaLabel}
            disabled={option.disabled}
            tabIndex={index === focusable ? 0 : -1}
            data-segmented-option={option.value}
            className={segmentedItemClass(active, size)}
            onClick={() => onValueChange(option.value)}
            onKeyDown={(event) => {
              const step = KEY_STEPS[event.key]
              if (step === undefined) return
              event.preventDefault()
              move(index, step)
            }}
          >
            {option.icon}
            {option.label}
          </button>
        )
        return iconOnly ? (
          <Hint key={option.value} label={option.ariaLabel}>
            {item}
          </Hint>
        ) : (
          item
        )
      })}
    </div>
  )
}
