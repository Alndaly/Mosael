/**
 * 「看起来像输入框的下拉触发器」的唯一样式来源。
 *
 * Select / Combobox / SearchableSelect 在界面上是同一类控件(点开选一个值),用户并排看到时
 * 理应一模一样。此前它们各写各的:Select 手写了这串,Combobox 借用 `<Button variant="outline">`
 * —— 而按钮的默认尺寸是 `rounded-full px-4` 的胶囊,于是同一张表单里出现圆角不同、左右留白
 * 不同、箭头图标也不同的两种"下拉框"。
 *
 * **两级 min-w-0 缺一不可**:值 span 是 flex 子项,触发器自身又常是 grid/flex 子项,
 * `min-width:auto` 会把它钉在内容最小宽度上 —— 长模型 id(doubao-seedance-1-0-pro-250528)
 * 会把整个面板顶穿,truncate 完全不生效,右侧箭头被挤没。都归零后 w-full 才真正生效。
 */
export const FIELD_TRIGGER_CLASS =
  "flex h-9 w-full min-w-0 items-center justify-between gap-1.5 whitespace-nowrap rounded-md border border-input bg-field px-3 py-2 text-ui-sm ring-offset-background data-[placeholder]:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&>span]:min-w-0 [&>span]:truncate";
