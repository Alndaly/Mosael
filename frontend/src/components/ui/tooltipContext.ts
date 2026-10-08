/**
 * 悬停说明那几个 context:根上的 Provider 标记、Truncate 往 Hint 里登记全文的范围、内嵌浏览器外壳那一块「区域」。
 *
 * **单独一个模块、只依赖 React**(app/contextIdentity.test.ts):context 的身份就是那一次 `createContext` 返回的对象,
 * 它所在的模块被热更新重跑一次就换出一个新的 —— 外层的 Provider 还是旧的,之后挂上的消费者拿到新的。此前它们住在
 * tooltip.tsx 里,而 tooltip.tsx 引着键帽(kbd.tsx)这些界面组件。
 */
import * as React from "react"

export type Side = "top" | "bottom" | "left" | "right"

/**
 * 应用根上的 Provider 顺手挂一个标记。Hint / Truncate 在没有 Provider 的地方(单独渲染一个组件的
 * 测试、孤立挂载的浮层)自己补一个,而不是像 Radix 那样抛错 —— 抛错的话,每个用到图标按钮的
 * 组件测试都得先包一层 Provider,漏一层就是一条与被测功能无关的红。
 *
 * 只是兜底:补出来的那个 Provider 只管它自己,一排按钮之间「移过去立刻出」(skipDelayDuration)
 * 要靠外面那个共同的 Provider。应用里永远有(App.tsx)。
 */
export const ProviderMark = React.createContext(false)

/**
 * Hint 的触发区里有会被截断的字(Truncate)时,**说明只出一条**:那段字被截断了,就把全文并进
 * 这条说明里;它带着补充的一句(Truncate 的 `hint`:完整地址、报错原文)时,那一句也并进来 ——
 * 而不是在同一处再挂一个说明。两条说明叠在同一块上,同一时刻只留一条的规则会让其中一条永远出不来
 * (要么看不到全文和原文,要么看不到补充说明)。
 *
 * Truncate 在这个范围里就不自己出说明,只登记「我现在被截断了吗、全文是什么、补充哪一句」。范围由说明的触发器
 * (TooltipTrigger)给:Hint 收下这些登记;直接用 Tooltip 的富内容卡片(引用卡片)不收 —— 那张卡片就是这块的说明,
 * 里面被截断的名字不另出一条。自己没话说的 Hint 套在另一条说明里时把范围原样往里传(见 Hint)。
 *
 * 浮层内容(Popover / Select / ContextMenu / Dialog 的 Content)会把范围清掉:React 的 context 会穿过
 * portal,不清的话,一个套在 Hint 里的组件弹出来的菜单项也会把全文交给外面那条够不着它的说明。
 */
export type ScopedText = () => { full: React.ReactNode | null; hint: string | null }
export type ScopeRegister = (get: ScopedText) => () => void
export const HintScope = React.createContext<ScopeRegister | null>(null)

/**
 * 说明浮层所在的「区域」:**内嵌浏览器的外壳**(顶栏、页面列表、侧栏)。外壳旁边就是原生网页视图,盖在一切 DOM
 * 上,DOM 里的说明伸进网页那一块就看不见 —— 所以区域里的说明交给浮层视图画在网页上面(见 useFloatMirror),
 * 想往哪边出就往哪边出。`side` 是这块里的说明默认往哪边出(顶栏往下、页面列表往右),控件自己给了方向就听控件的。
 *
 * 没有浮层视图(网页版,没有原生视图)时照旧画在 DOM 里;外壳的 z 比所有浮层(styles.css 统一定成 120)都高,
 * 所以标上 `data-over-chrome`,styles.css 据此把它那层抬到外壳之上。
 */
export type HintRegionValue = {
  side?: Side
  /**
   * `lightbox`:全屏看大图那一层(z-220,压在外壳上面)里的说明。那时原生网页视图已经让开了(见 nativeViewAside),
   * 说明照常画在 DOM 里,只是层要抬到大图之上(标 `data-over-lightbox`,styles.css 据此抬层),不交给浮层视图。
   */
  layer?: "lightbox"
}
export const HintRegion = React.createContext<HintRegionValue | null>(null)
