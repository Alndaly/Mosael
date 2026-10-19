/**
 * 编辑器工具条上的胶囊按钮样式。**一份**。
 *
 * 这串类名此前在逐字稿面板里抄了九遍(那次收成了文件内的一个常量),字幕面板又照着抄了三遍 ——
 * 同一个形状散在两个文件里,改一处就意味着两处开始不一样。放在这里,两边都指向它。
 */
export const PILL =
  "inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md border border-transparent bg-control px-[9px] text-ui-xs text-muted-foreground transition-[color,border-color,background] duration-160 enabled:hover:bg-secondary enabled:hover:text-foreground disabled:cursor-default disabled:opacity-45 [&_em]:rounded-full [&_em]:bg-[color-mix(in_oklab,currentColor_14%,transparent)] [&_em]:px-[5px] [&_em]:text-ui-2xs [&_em]:not-italic [&_em]:tabular-nums";

/**
 * 顶部动作条上的**图标**动作。和 PILL 同一档高度(32px)、同一档图标(16px),只是没有文字 ——
 * 名字由 `IconButton` 的 `label` 交给读屏和 Hint。
 *
 * - `relative`:计数角标(见 CountBadge)钉在右上角;
 * - `shrink-0`:窄面板里整颗折行,而不是被 flex 压成点不到的窄条(工具栏本身 `flex-wrap`)。
 */
export const ACTION_ICON = "relative shrink-0 text-muted-foreground";
