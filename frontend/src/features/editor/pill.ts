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

/**
 * 顶部动作条本身:窄了就**按单元折行**,不横向滚。
 *
 * 动作从「图标 + 文字」收成只有图标之后,一排同款方钮彼此看起来一样 —— 谁和谁是一类
 * 只剩布局能说。所以分组做成看得见的三件事:组内 4px(`ACTION_GROUP`)、组间一条发丝线、
 * 线两侧各 6px(`ACTION_UNIT`,加上线本身两家之间 13px)。这里 `gap-x-1.5` 管的是单元之间。
 */
export const ACTION_BAR = "flex flex-wrap items-center gap-x-1.5 gap-y-1.5";

/**
 * 一组同类动作:组内 4px。组本身不折行 —— 折行单位是外面的 `ACTION_UNIT`,
 * 这样"近的是同类、远的是异类"在窄宽度下也成立。
 */
export const ACTION_GROUP = "flex items-center gap-1";

/**
 * 一组动作 + 它前面那条发丝线,包成**一个不折行的单元**。
 *
 * 分隔线不能直接挂在 `flex-wrap` 的栏上:栏在组与组之间折行时,一条孤零零的线会掉到下一行行首,
 * 读起来像"这一行第一颗按钮属于谁"的杂音。把它和后面那一组放进同一个 `inline-flex` 单元,
 * 线就永远跟着自己的组走;栏只在单元之间折行。
 */
export const ACTION_UNIT = "inline-flex shrink-0 items-center gap-1.5";

/** 组与组之间那条 1px 发丝线(装饰,不参与读屏)。 */
export const ACTION_DIVIDER = "h-4 w-px shrink-0 bg-border";
