/**
 * 编辑器工具条上的胶囊按钮样式。**一份**。
 *
 * 这串类名此前在逐字稿面板里抄了九遍(那次收成了文件内的一个常量),字幕面板又照着抄了三遍 ——
 * 同一个形状散在两个文件里,改一处就意味着两处开始不一样。放在这里,两边都指向它。
 */
export const PILL =
  "inline-flex h-6 cursor-pointer items-center gap-[5px] rounded-full border border-border bg-background px-[9px] text-ui-xs text-muted-foreground transition-[color,border-color,background] duration-[120ms] enabled:hover:border-ring enabled:hover:text-foreground disabled:cursor-default disabled:opacity-45 [&_em]:rounded-full [&_em]:bg-[color-mix(in_oklab,currentColor_14%,transparent)] [&_em]:px-[5px] [&_em]:text-ui-2xs [&_em]:not-italic [&_em]:tabular-nums";
