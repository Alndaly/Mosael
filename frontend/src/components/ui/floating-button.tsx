import * as React from "react"

import { IconButton, type IconButtonProps } from "@/components/ui/icon-button"
import { cn } from "@/lib/utils"

/**
 * 浮在画面(照片、视频、暗底)上的圆钮:灯箱右上角的关闭 / 保存到本地,对比视图里浮在画面上的那几颗。
 *
 * 这一套外观此前**手写在调用处**(灯箱的关闭键那一长串 className),旁边后来加的「保存到本地」为了不涨
 * `design/controlOverrides` 的存量走的是 `variant="secondary" size="icon-sm"` —— 一颗跟主题走的实心方角钮、
 * 一颗是浮在暗底上的半透明圆钮,并排放在同一处,位置、形状、底色、大小没一样对得上(维护者报的)。
 *
 * 浮在**媒体上**的钮本来就该是另一种控件:底下是照片或视频,用跟随主题的表面色,浅色主题下就是一圈白底白描边
 * 糊在画面上;所以它固定是「半透明黑底 + 白字 + 全圆、无描边」,而且**只有一档大小**(36px,图标 18px)——
 * 同一处不会再有第二种尺寸,也就不会又长回两套样子。要另一种,是另一个基础件,不是在这里加参数。
 *
 * 位置的两种给法:
 * - **画面右上角那一排**(灯箱):给 `slot`,`0` 贴右边缘、往左一颗一颗排。同一顶边、同一层,间距由这里的表算
 *   (`FLOATING_TOP_RIGHT`),调用方不各写一遍 —— 并排的两颗钮对不齐,几乎都是因为各自写了一份位置;
 * - **别处**(窗格里、跟着画面缩放的):不给 `slot`,位置自己用 className 摆 —— 那处的相对位置只有它自己知道。
 *
 * 棘轮:`design/controlOverrides.test.ts` 的 OWNERS 认得 `components/ui/`,高度、圆角、图标大小写在这个文件里
 * 是**该写的**;用它的地方只给名字和位置,不再往 className 上压尺寸(灯箱那处因此从存量 1 减到 0)。
 */
/** 一档浮钮的全部外观:36px 圆、半透明黑底、白字、悬停提亮、白色焦点圈、图标 18、桌面端不当拖拽区。 */
export const FLOATING_BUTTON =
  "grid size-9 cursor-pointer place-items-center rounded-full border-0 bg-[rgb(0_0_0/0.38)] text-[rgb(255_255_255/0.88)] transition-colors hover:bg-[rgb(255_255_255/0.2)] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[rgb(255_255_255/0.8)] [&_svg]:size-[18px] [.is-desktop_&]:[-webkit-app-region:no-drag]"

/** 一颗浮钮的直径(36px,`size-9`)。图标 18px 写在 {@link FLOATING_BUTTON} 里(调用方不写 `size`)。 */
export const FLOATING_SIZE = 36

/** 并排两颗浮钮之间留的空:8px(栅格上的 `gap-2`)。 */
export const FLOATING_GAP = 8

/**
 * 画面**右上角**一排钮的落位:`0` 贴右边缘(`right-2` = 8px),往左每一颗退「一颗钮 + 8px」。
 *
 * 8 + 36 + 8 = 52,所以第二颗是 `right-[52px]` —— Tailwind 的刻度里没有 13 这一档,这里写实值。
 * `z-[221]`:压在大图那一层(`z-[220]`)上面,两颗同在那一层。再加一颗钮就往这张表末尾加一条。
 */
export const FLOATING_TOP_RIGHT = [
  "fixed right-2 top-1.5 z-[221]",
  "fixed right-[52px] top-1.5 z-[221]",
] as const

//: `slot` 要从 IconButton(即 React 的按钮属性)里去掉:HTML 自己有个 `slot`(字符串,分配落点),
//: 这里要的是「右上角那一排的第几颗」(下标),不 Omit 掉两个类型会撞成 never。
export type FloatingIconButtonProps = Omit<IconButtonProps, "unstyled" | "variant" | "size" | "shape" | "slot"> & {
  /** 右上角那一排里的第几颗(`0` = 贴右边缘)。不给就自己用 `className` 摆位置。 */
  slot?: number
}

/**
 * 浮在画面上的圆钮。名字、说明、快捷键、禁用原因照旧走 {@link IconButton}(也就有 `aria-label` 和悬停说明);
 * 外观一律用 {@link FLOATING_BUTTON},图标自带 18px —— 调用方只给名字、位置和点下去做什么。
 */
const FloatingIconButton = React.forwardRef<HTMLButtonElement, FloatingIconButtonProps>(
  ({ slot, className, ...props }, ref) => (
    <IconButton
      unstyled
      ref={ref}
      {...props}
      className={cn(FLOATING_BUTTON, slot === undefined ? undefined : FLOATING_TOP_RIGHT[slot], className)}
    />
  ),
)
FloatingIconButton.displayName = "FloatingIconButton"

export { FloatingIconButton }
