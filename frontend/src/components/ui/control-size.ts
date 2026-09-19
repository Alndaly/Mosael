/**
 * 表单控件的**高度刻度**。按钮、输入框、下拉触发器都从这里取 —— 一行里、一张表单里并排的
 * 控件理应同高,而同高不能靠"三个文件碰巧都写了 h-10"。
 *
 * 此前正是那样:button 的默认尺寸、input、field-trigger 各写一个 `h-10`,今天相等只是巧合;
 * SearchableSelect 手抄过一份 `h-8`,在插件的「新建连接」那一行里比旁边矮了 8px(见
 * fieldTrigger.consistency.test.ts)。棘轮 `controlSize.test.ts` 拦下这几个文件里再手写高度。
 */
export const CONTROL_HEIGHT = {
  /** 28px:工具栏的实际刻度(时间线、编辑器、智能体输入框)。 */
  xs: "h-7",
  /** 32px:卡片、窄面板里的次要动作。 */
  sm: "h-8",
  /** 40px:表单、对话框底部 —— 输入框、下拉框、按钮的默认高度。 */
  md: "h-10",
  /** 44px:少数需要更醒目的主动作。 */
  lg: "h-11",
} as const;

/** 方形图标按钮:边长与同档文字控件相同,并排时不高出一截。 */
export const CONTROL_SQUARE = {
  xs: "size-7",
  sm: "size-8",
  md: "size-9",
} as const;
