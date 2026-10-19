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
 * - `shrink-0`:左栏横向滚动时整颗按自己的宽度走,不被压成点不到的窄条。
 */
export const ACTION_ICON = "relative shrink-0 text-muted-foreground";

/**
 * 顶部动作条:**左右两栏**。
 *
 * 左栏是动作,右栏是一段不会走开的信息(逐字稿的「N 句 · M 字」/ 字幕的「字幕样式」)。
 * 维护者要的是「右侧信息 sticky 在右侧,左侧超出滚动即可」:右边按内容定宽、永远贴在右缘;
 * 左边是那条可收缩的栏,放不下时自己横滚 —— 右边那份信息不参与滚动。
 *
 * **这里的横滚是用户明确要的**,和别处「宁可折行也不横滚」不冲突:别的工具行里全是要读、
 * 要打的控件,滚起来就藏掉一半,而它们没有主次(见 MediaLibraryView 的筛选行);这一排则是
 * 同一类的图标动作,右侧那条信息才是要一直看得见的那一个 —— 让它留在原地,动作从左往右翻。
 */
export const ACTION_BAR = "flex min-w-0 items-center gap-2.5";

/**
 * 左栏:可收缩的动作区。`flex-1 min-w-0` 先让它成为能被压缩的那一栏 —— 不写 `min-w-0`,
 * flex 的自动最小宽度会按内容把它撑住,右栏就被挤出面板。`overflow-x-auto` 只在真放不下时
 * 出现滚动;`overflow-y-hidden` 保证永远只有横向那一条。
 *
 * **裁剪框自己也要留纵向余量** ✓。`overflow-x: auto` 会让 `overflow-y: visible` 计算成 `auto`
 * (溢出即裁),`overflow-y-hidden` 更是直接裁 —— 裁剪发生在 **padding box 边缘**,所以要让
 * 凸出来的东西落在**内边距**里,而不是去改 `overflow-y`(和 `overflow-x-auto` 同时写 `visible`
 * 不算数,只会变成 `auto` 照样裁、还多一条纵向滚动条)。
 *
 * 具体量:图标钮 `icon-sm` 32px;`CountBadge` 按设计钉在图标右上 `-top-1`(向上凸 4px);
 * 按钮的 `ring-2` 焦点环往上下各出 2px。够用的裁切框 = 32 + 4(上)+ 2(下)= 38px;
 * 取 `py-1`(上下各 4px)= 40px,正好压在控件刻度的 md 档,底边还多 2px 给焦点环 ——
 * `min-h-10` 把这条下限钉住,以后谁改小内边距,测试先红。
 *
 * 只补这几像素:行高从 32 变 40(+8px),不再往别处找地方。
 *
 * 滚动条的样子走全局策略(见 design/tokens.css:平时宽 0,悬停 / 聚焦才显形,桌面壳里是
 * overlay 不占布局),所以这里**不设 `scrollbar-gutter`** —— 那会常驻一条高度;也不用 `calc()`。
 */
export const ACTION_SCROLL = "flex min-h-10 min-w-0 flex-1 items-center overflow-x-auto overflow-y-hidden py-1";

/**
 * 左栏里的动作轨道:一排、不折行、宽度按内容(`w-max`)。
 *
 * **不折行是横滚的前提** —— 折行的 flex 容器不会产生横向溢出,`overflow-x-auto` 就永远不滚,
 * 被压窄的只会是会收缩的右栏。滚动量发生在 `ACTION_SCROLL` 那一层,轨道自己的结构不动。
 */
export const ACTION_TRACK = "flex w-max items-center gap-x-1.5";

/**
 * 右栏:统计文字 / 「字幕样式」。钉在右缘 —— 不参与收缩(`shrink-0`)、不滚、不折行
 * (`whitespace-nowrap`)。`self-stretch` 让那条 `border-l` 跟左边的图标同高(整条栏的
 * 内容高度),而不是只绕着一行 16px 的统计文字。这条线和组间的 `ACTION_DIVIDER` 同一种细线。
 *
 * `min-h-10` 和左栏同一档:左边为了角标 / 焦点环钉在 40px,右栏也跟着这一档 —— 里面的
 * 32px 图标钮上下各 4px,「字幕样式」的焦点环不贴边;两条栏的 `border-l` 也不会一高一低。
 */
export const ACTION_INFO = "flex min-h-10 shrink-0 self-stretch items-center gap-2 whitespace-nowrap border-l border-border pl-2.5";

/**
 * 一组同类动作:组内 4px。组本身不折行 —— 单元结构决定的,见 `ACTION_UNIT`。
 */
export const ACTION_GROUP = "flex items-center gap-1";

/**
 * 一组动作 + 它前面那条发丝线,包成**一个不折行的单元**。
 *
 * 分组是看得见的:线就长在这一组前面,而不是栏上的一颗独立元素。动作轨道横向滚动时,
 * 滚到哪线都跟着自己的组;哪天轨道改回折行,线也不会孤零零掉到下一行行首、读起来像
 * 「这一行第一颗按钮属于谁」的杂音。
 */
export const ACTION_UNIT = "inline-flex shrink-0 items-center gap-1.5";

/** 组与组之间那条 1px 发丝线(装饰,不参与读屏)。 */
export const ACTION_DIVIDER = "h-4 w-px shrink-0 bg-border";
