/**
 * 控件的**刻度**:高度、方钮边长、留白、字号、图标大小、圆角。按钮、字段(输入框、下拉触发器、文本域)、分段控件、
 * 胶囊筛选、单选都只从这里取值 —— 一行里、一张表单里并排的控件理应同高,而同高不能靠"三个文件碰巧都写了 h-10"。
 * 规格(哪种场景用哪一档)见 docs/DESIGN_LANGUAGE.md;样张在开发构建的 `#/dev/design`。
 *
 * 此前正是那样:button 的默认尺寸、input、field-trigger 各写一个 `h-10`,今天相等只是巧合;
 * SearchableSelect 手抄过一份 `h-8`,在插件的「新建连接」那一行里比旁边矮了 8px(见
 * fieldTrigger.consistency.test.ts)。棘轮 `controlSize.test.ts` 拦下这几个文件里再手写高度,
 * `design/controlOverrides.test.ts` 拦下业务代码在 className 里改高度、留白、圆角、字号。
 */
export const CONTROL_HEIGHT = {
  /** 28px:密集工具条(时间线、内嵌浏览器顶栏、智能体输入框底栏、弹出层里的小工具行)。 */
  xs: "h-7",
  /** 32px:画布工具条、窗口顶栏、卡片里和列表行尾的次要动作、面板标题栏。 */
  sm: "h-8",
  /** 40px:填值的地方 —— 表单、对话框、侧栏面板、设置行、页头动作。按钮、字段的默认档。 */
  md: "h-10",
  /** 44px:整页只有一个动作的地方(登录、首次引导);页签那一条也是这个高度。 */
  lg: "h-11",
} as const;

export type ControlTier = "xs" | "sm" | "md";

/**
 * 方形图标按钮:边长和同档文字控件**一样**,并排时不高出、不矮一截。
 *
 * md 此前是 36(`size="icon"`),比同档 40 的输入框、按钮矮 4px;挨着字段的试听键只好另起一档 40(`icon-lg`)。
 * 2026-10 定稿:md 就是 40,两档合成一个名字 `icon`(docs/DESIGN_LANGUAGE.md「刻度」)。
 */
export const CONTROL_SQUARE: Record<ControlTier, string> = {
  xs: "size-7",
  sm: "size-8",
  md: "size-10",
};

/**
 * 按钮里的图标多大。**文字按钮跟着档位**:xs(28px 高、12px 字)里 16px 的图标比字重,用 14;sm、md 用 16。
 * **只有图标的按钮在哪一档都是 16**(图标就是它的全部内容,缩小了就是更难点中、更难认)—— IconButton 自己钉住。
 * 写在图标上的 `size={12}` 不生效:这里是 CSS,盖过 SVG 的 width/height 属性。
 */
export const CONTROL_ICON = {
  text: { xs: "[&_svg]:size-3.5", sm: "[&_svg]:size-4", md: "[&_svg]:size-4" } satisfies Record<ControlTier, string>,
  square: "[&_svg]:size-4",
} as const;

/**
 * 字段(输入框、下拉触发器)的**档位**:高度 + 左右留白 + 字号一起走,和 `buttonVariants` 的
 * xs/sm/default 是同一把尺 —— `<Input size="sm">` 挨着 `<Button size="sm">`,同高是构造出来的,
 * 不是两边碰巧都写了 `h-8`。字号跟着高度走:28px 的框里 text-ui-sm 会把字顶满。
 *
 * 没有 lg:字段没有「更醒目」的需要。棘轮:`design/fieldScale.test.ts`、`design/fieldTiers.test.ts`(同一个容器里同档)。
 */
export type FieldSize = ControlTier;

export const FIELD_SIZE: Record<FieldSize, string> = {
  xs: `${CONTROL_HEIGHT.xs} px-2 text-ui-xs`,
  sm: `${CONTROL_HEIGHT.sm} px-2.5 text-ui-sm`,
  md: `${CONTROL_HEIGHT.md} px-3 text-ui-sm`,
};

/** 文本域:和 md 字段同一套留白、字号;高度随内容,最矮 60px(约三行)。 */
export const FIELD_TEXTAREA = "min-h-[60px] px-3 py-2 text-ui-sm";

/**
 * 字段出错(`aria-invalid="true"`):描边和聚焦环换成危险色。错误那句话在字段下面(FormMessage 的样子:12px 红字)。
 * 输入框、文本域、下拉触发器都挂它 —— 出错时只有下面那行红字、字段本身不变色,眼睛扫一张表单找不到是哪一格。
 */
export const FIELD_INVALID =
  "aria-invalid:border-destructive aria-invalid:focus:ring-destructive aria-invalid:focus-visible:ring-destructive";

/**
 * 分段控件(两到五个互斥选项、选项短、切换立刻生效)的三档。**总高度跟档位**,和同一行的按钮、字段一样高:
 * 外壳 = 次级底色 + 内边距,里面一项的圆角 + 内边距 = 外壳的圆角(md:8 + 4 = 12;sm、xs:6 + 2 = 8)。
 * 此前只有 40 这一档,各处在 className 里压成 36、32、28、24 等六种样子。
 */
//: 外壳不写高度:一项的高度 + 上下内边距就是这一档(32 + 4 + 4 = 40),选项多到折行时外壳跟着长。
export const SEGMENTED_SIZE: Record<ControlTier, { list: string; item: string }> = {
  xs: { list: "gap-0.5 rounded-md p-0.5", item: "h-6 rounded-sm px-2 text-ui-xs [&_svg]:size-3.5" },
  sm: { list: "gap-0.5 rounded-md p-0.5", item: `${CONTROL_HEIGHT.xs} rounded-sm px-2.5 text-ui-xs [&_svg]:size-3.5` },
  md: { list: "gap-1 rounded-lg p-1", item: `${CONTROL_HEIGHT.sm} rounded-md px-3 text-ui-sm [&_svg]:size-4` },
};

/** 行内动作(Button `variant="inline"`):高 24、上下各收 2px(不撑高所在的那一行),12px 字、14px 图标。 */
export const INLINE_ACTION_SIZE = "h-6 -my-0.5 gap-1 rounded-sm px-1.5 py-0 text-ui-xs [&_svg]:size-3.5";

/** 胶囊筛选:一排可以折行的筛选条件。高 28(和 xs 对齐),全圆,12px 字,图标 12px。 */
export const CHIP_SIZE = `${CONTROL_HEIGHT.xs} rounded-full px-2.5 text-ui-xs [&_svg]:size-3`;
