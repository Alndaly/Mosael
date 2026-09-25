import { WINDOW_CHROME_HEIGHT } from "@/lib/windowChrome";

/** Shared visual language; focus management belongs to each primitive. */

/**
 * 浮层躲避碰撞时的边距 —— **顶部要让出整条顶栏**,不只是窗口边缘。
 *
 * Radix 只知道视口,不知道顶栏:它会把一个向上翻的下拉稳稳地放在顶栏底下。而顶栏在桌面端是
 * 窗口拖拽区(-webkit-app-region: drag),拖拽区由系统在页面之前截走输入,z-index 对它无效 ——
 * 于是落在那 56px 里的选项看得见、点不动(真机:节点里素材下拉的前几项)。
 * 所有带定位的浮层(Popover / Select / ContextMenu / Tooltip)默认都用它;调用方给了自己的
 * collisionPadding 就以调用方为准。
 */
export const FLOATING_COLLISION_PADDING = { top: WINDOW_CHROME_HEIGHT + 8, right: 8, bottom: 8, left: 8 } as const;
/**
 * 浮层的表面。`floating-surface` 这个类名不是装饰:tokens.css 用它把 `--divider` 换成
 * 贴着**这层**表面算的那一版 —— 页面的分隔色画到 popover 上就消失了(深色下
 * `--popover: #292c30` 对 `--divider: #292d33`,实测对比 1.013),而菜单里的分组线正是它画的。
 * 和 `.modal-surface` 改写 `--field`/`--control` 是同一个手法:表面负责宣布"在我这层,这几个
 * 语义色该取什么值",调用方照旧写 `border-divider`。
 */
export const FLOATING_SURFACE = "floating-surface rounded-lg border border-floating-border bg-popover text-popover-foreground shadow-[var(--shadow-floating)]";
export const FLOATING_MOTION = "duration-150 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0 motion-reduce:animate-none motion-reduce:transition-none";
export const MODAL_SURFACE = "modal-surface rounded-2xl border border-[var(--modal-border)] bg-[var(--modal-surface)] text-popover-foreground shadow-[var(--shadow-modal)]";
export const MODAL_OVERLAY = "modal-overlay [.is-desktop_&]:[-webkit-app-region:no-drag] fixed inset-0 z-50 bg-[var(--overlay-modal)]";
export const MODAL_TITLE = "m-0 text-ui-lg font-semibold leading-snug tracking-tight break-words";
export const MODAL_DESCRIPTION = "text-ui-sm leading-relaxed text-muted-foreground break-words";
const MENU_ITEM_SHAPE = "relative flex min-h-9 cursor-default select-none items-center gap-2.5 rounded-md px-2.5 py-2 text-ui-sm leading-5 outline-none transition-colors";
const MENU_ITEM_STATES = "data-[highlighted]:bg-secondary disabled:pointer-events-none disabled:opacity-40 data-[disabled]:pointer-events-none data-[disabled]:opacity-40 [&_svg]:size-4 [&_svg]:shrink-0";
export const MENU_ITEM = `${MENU_ITEM_SHAPE} hover:bg-secondary focus:bg-secondary ${MENU_ITEM_STATES}`;
/**
 * 自己管着「高亮哪一行」的菜单用这一版:和 MENU_ITEM 同一副样子,只是底色**只**看
 * `data-highlighted`。这种菜单只有一个高亮下标 —— 指针移到哪行、方向键走到哪行都改它 ——
 * 再叠一层 `hover:` 底色的话,方向键走开之后,指针还停着的那一行也亮着,一张单子上两行高亮。
 */
export const MENU_ITEM_ROVING = `${MENU_ITEM_SHAPE} ${MENU_ITEM_STATES}`;
/**
 * 菜单里的破坏性条目(删除、移除…):叠在 MENU_ITEM 上,只换字色 —— 行高、内边距、悬停底色
 * 都和别的条目一样,**不加描边、不换底色**。和右键菜单里 `text-destructive focus:text-destructive`
 * 那一种是同一句话;悬停 / 键盘高亮时也保持红字,不被 hover 的前景色盖回去。
 */
export const MENU_ITEM_DESTRUCTIVE = "text-destructive hover:text-destructive focus:text-destructive data-[highlighted]:text-destructive";
/** 菜单里分组之间那条线。颜色走 `--divider` —— 浮层自己会把它改成贴合这层表面的值(见 tokens.css 的 `.floating-surface`)。 */
export const MENU_SEPARATOR = "mx-2 my-1.5 h-px bg-divider";

/**
 * 浮层列表里行与行之间那条线。**是一个独立的元素,不是行的 border。**
 *
 * 用 `divide-y` 会把线画成上一行的 `border-bottom`,而这些行为了 hover 高亮都带着
 * `rounded-lg` —— border 跟着圆角走,于是那条"横线"两端是翘起来的弧。看着像画歪了。
 * 一个独立的 1px 块不受圆角影响,左右还能自己收进来一点,读起来才是分组线而不是描边。
 */
export const LIST_HAIRLINE = "mx-2 h-px shrink-0 bg-divider";
/** For small button-driven action popovers; forms and inspectors keep their own layout. */
export const ACTION_MENU = "grid gap-0.5 p-1.5 [&>button]:h-9 [&>button]:justify-start [&>button]:rounded-md [&>button]:px-2.5 [&>button]:text-ui-sm [&>button]:font-normal [&>button]:shadow-none [&>button:hover]:bg-secondary";
export const MODAL_FOOTER = "flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-end [&_button]:h-10 [&_button]:rounded-md [&_button]:px-4 [&_button]:text-ui-sm";
