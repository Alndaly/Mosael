/**
 * 智能体时间线里**一行**的几何。
 *
 * 一次工具调用、一段思考、一句「正在思考」,在读的人眼里是同一类东西:这一步在做什么。
 * 它们必须共用同一个左缘、同一个图标栏、同一个字号 —— 差 4px 也看得出来,而且看起来像是
 * "这几行不属于同一件事"。此前它们各写各的:工具行 `gap-2`,思考块 `gap-1`,而画布助手那句
 * 「智能体思考中…」根本不是一行标记 —— 没有内缩,字号从外层继承成了 text-ui-md,比上面
 * 每一行都大一号。
 *
 * ## 为什么 gap 是 1 而不是 2
 *
 * 这一栏只有一个内容起点,标题和展开的正文都得落在它上面:
 *
 *     px-1.5(6) + MarkerIcon(16) + gap-1(4)              = 26px  ← 标题文字
 *     ml-[13px](13) + border-l(1) + pl-3(12)              = 26px  ← 展开的正文
 *
 * 而 13px 这个位置不是凑出来的:图标槽是 6..22,竖线正落在它的中线上,展开的明细看起来才是
 * "从这一步垂下来的"。改成 gap-2 的话标题会右移 4px、和自己的正文错开;把竖线挪到 17px
 * 又会让它离开图标中线。所以两个数一起定,改一个就得改另一个 —— 这段算术写在这里,
 * 免得下次有人只看见"gap 不一致"就把它抹平(我就干过一次)。
 */

/**
 * **时间线这一栏的字号。**
 *
 * 助手的正文是 `text-ui-md`(16px),而工具步骤、思考、结果卡说的是"机器那一侧发生了什么" ——
 * 它们该比正文小一档,否则一条工具返回的清单会比回答本身还抢眼(实测:`list_scenes` 返回的
 * 七个场景名,每行都和正文一样大,整段读起来像正文被一列文件名打断了)。
 *
 * 此前没有任何地方写下这个字号,于是它**从外层继承**成了 16px。文件开头那段说的「画布助手那句
 * 『智能体思考中…』字号从外层继承成了 text-ui-md」是同一个毛病的另一处 —— 那次是单独给那一行
 * 补了字号。补一处、漏一处,所以这次挂在"一行"这个概念上:谁用这几个类,谁就是这一栏里的一行。
 *
 * **只定这一档。** 行内更次要的东西(耗时、标签、代码块)各自显式写 `text-ui-xs` / `2xs`,
 * 层级仍在;没写的就跟这一档,而不是跟正文。
 */
export const AGENT_ROW_TEXT_CLASS = "text-ui-sm";

/** 行外框。配 `<Marker className={AGENT_ROW_CLASS}>` 用。 */
export const AGENT_ROW_CLASS = "gap-1 rounded-md px-1.5 py-1 text-ui-sm";

/**
 * 行内图标。**显式给 size-3**:Marker 会把没有 size- 类的 svg 统一撑到 16px,
 * 而这一行的节奏是按 12px 图标定的。
 */
export const AGENT_ROW_ICON_CLASS = "size-3";

/** 展开的明细:挂在一条从图标中线垂下来的竖线上,正文和标题同一个起点。 */
export const AGENT_ROW_BODY_CLASS = "ml-[13px] border-l border-border pl-3 text-ui-sm";

/**
 * 正文块的外框,让它和标记行**在纵向上算同一种块**。
 *
 * `py-1` 在标记行上是**热区**:鼠标扫过时那块底色要比文字大一圈。但它同时把行的盒子撑高了
 * 8px,而正文段落没有 —— 于是外层那一个统一的 gap 落到眼睛里就变成了三个值。实测(780px 宽、
 * 一轮「思考 → 正文 → 两步工具 → 思考 → 正文」):
 *
 *     正文 ↔ 标记行     18px
 *     标记行 ↔ 正文     18.5px
 *     标记行 ↔ 标记行   22px      ← 两边各带一份内边距
 *
 * 同一段对话里"一个空行"有三种宽度,而这三个数没有任何一处代码写下过。给正文块补上同一份
 * 内缩,块与块之间就只剩容器那一个 gap 说了算;容器的 gap 相应收窄,好让最常见的那一档
 * (18px)保持不变,只把 22 那一档收回来。
 *
 * **块之间比块内部松**是有意的:markdown 自己的段落间距是 10px,而块与块隔的是"这是另一件
 * 事" —— 一步工具、一段思考、一段回答。两者相等的话,一轮回答会读成一整片没有停顿的东西。
 */
export const AGENT_TEXT_BLOCK_CLASS = "py-1";

/**
 * 一轮回答里几块(思考、正文、工具行)排成的那一列:单列 grid、块与块之间 gap-1.5(见 AgentTurnContent 的说明)。
 * 骨架(ChatTranscriptSkeleton)用同一个类,内容到了原地换上。
 */
export const AGENT_TURN_BLOCKS_CLASS = "grid w-full min-w-0 grid-cols-[minmax(0,1fr)] gap-1.5";

/**
 * 气泡下面那一行脚注的外框(悬停才显形,但一直占着高度)。骨架照它留一行,内容到了不挪位置。
 *
 * **最低高度 = 一个脚注动作的高度**(FOOTER_ACTION_CLASS:一行字 + 上下 py-0.5)。按钮的字号、行高都继承这一行
 * (`button{font:inherit}`),所以写成 `1lh + 0.25rem` 在任何行高下都和那颗「复制」一样高 —— 有没有按钮,这一行都一样高;
 * 此前写死 18px,骨架那一行(没有按钮)比真的(有「复制」)矮 4px,内容一到下面整块往下跳 4px。
 */
export const MESSAGE_FOOTER_ROW_CLASS = "mt-1.5 flex min-h-[calc(1lh+0.25rem)] items-center gap-1.5 text-ui-xs";

/** 助手那一轮占的那一列(ChatBubble 和骨架共用;骨架换成真内容时不挪位置)。 */
export const CHAT_ASSISTANT_ROW_CLASS = "relative mx-auto w-full max-w-[780px] shrink-0 text-ui-md leading-[1.65] [word-break:break-word]";

/**
 * 用户气泡那一列。**items-end,不是 items-stretch。** 这一列里除了气泡还有悬停才显形的脚注(发出的时间 + 复制),
 * 它透明但占宽度;stretch 会把气泡拉到和脚注一样宽 —— 短消息右边平白多一截,而时间是相对的
 * (「刚刚」→「3 分钟前」,每 30 秒重算),脚注一变宽,气泡就跟着伸缩。气泡按自己的字定宽、靠右。
 */
export const CHAT_USER_ROW_CLASS = "ml-auto mr-[max(calc((100%-780px)/2),0px)] flex w-fit max-w-[min(560px,82%)] shrink-0 flex-col items-end";

/** 用户气泡本身(药丸)。 */
export const CHAT_USER_PILL_CLASS =
  "whitespace-pre-wrap rounded-lg rounded-br-[6px] bg-secondary px-3 py-[9px] text-ui-md leading-[1.65] text-foreground [word-break:break-word]";
