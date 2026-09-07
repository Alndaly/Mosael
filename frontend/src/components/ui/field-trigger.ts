/**
 * 「看起来像输入框的下拉触发器」的唯一样式来源。
 *
 * Select / Combobox / SearchableSelect 在界面上是同一类控件(点开选一个值),用户并排看到时
 * 理应一模一样。此前它们各写各的:Select 手写了这串,Combobox 借用 `<Button variant="outline">`
 * —— 而按钮的默认尺寸是 `rounded-full px-4` 的胶囊,于是同一张表单里出现圆角不同、左右留白
 * 不同、箭头图标也不同的两种"下拉框"。
 *
 * 右侧那枚箭头也归这里(`FIELD_TRIGGER_CHEVRON`):它和触发器是同一个视觉单元,分开写的
 * 结果是三处三个样子 —— 14px/opacity-60、14px/opacity-50、16px/opacity-50。并排时读者看不出
 * 是"三种控件",只看得出"这排东西没对齐"。
 *
 * **两级 min-w-0 缺一不可**:值 span 是 flex 子项,触发器自身又常是 grid/flex 子项,
 * `min-width:auto` 会把它钉在内容最小宽度上 —— 长模型 id(doubao-seedance-1-0-pro-250528)
 * 会把整个面板顶穿,truncate 完全不生效,右侧箭头被挤没。都归零后 w-full 才真正生效。
 */
export const FIELD_TRIGGER_CLASS =
  "flex h-10 w-full min-w-0 items-center justify-between gap-1.5 whitespace-nowrap rounded-md border border-field-border bg-field px-3 py-2 text-ui-sm ring-offset-background data-[placeholder]:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&>span]:min-w-0 [&>span]:truncate";

/** 触发器右侧的下拉箭头。尺寸与透明度跟着触发器走,三种控件同一个写法。 */
export const FIELD_TRIGGER_CHEVRON = "h-4 w-4 shrink-0 opacity-50";
