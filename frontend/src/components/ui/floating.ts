/** Shared visual language; positioning and focus management belong to each primitive. */
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
export const MENU_ITEM = "relative flex min-h-9 cursor-default select-none items-center gap-2.5 rounded-md px-2.5 py-2 text-ui-sm leading-5 outline-none transition-colors hover:bg-secondary focus:bg-secondary data-[highlighted]:bg-secondary disabled:pointer-events-none disabled:opacity-40 data-[disabled]:pointer-events-none data-[disabled]:opacity-40 [&_svg]:size-4 [&_svg]:shrink-0";
/** 菜单里分组之间那条线。颜色走 `--divider` —— 浮层自己会把它改成贴合这层表面的值(见 tokens.css 的 `.floating-surface`)。 */
export const MENU_SEPARATOR = "mx-2 my-1.5 h-px bg-divider";
/** For small button-driven action popovers; forms and inspectors keep their own layout. */
export const ACTION_MENU = "grid gap-0.5 p-1.5 [&>button]:h-9 [&>button]:justify-start [&>button]:rounded-md [&>button]:px-2.5 [&>button]:text-ui-sm [&>button]:font-normal [&>button]:shadow-none [&>button:hover]:bg-secondary";
export const MODAL_FOOTER = "flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-end [&_button]:h-10 [&_button]:rounded-md [&_button]:px-4 [&_button]:text-ui-sm";
