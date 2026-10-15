import * as React from "react";

import { SearchableSelect } from "@/components/ui/searchable-select";

/** 屏幕坐标(clientX / clientY)。 */
export interface ScreenPoint {
  x: number;
  y: number;
}

/**
 * 双击落在画布的**空白处**吗 —— 是就给出双击的屏幕坐标,否则 null。
 *
 * 只认 React Flow 的底板(`.react-flow__pane`):节点、连线、框选框、浮在画布上的面板都不算 —— 双击节点有它自己的意思
 * (工作流里是钻进循环体 / 子图),双击面板里的字是选词。
 */
export function emptyCanvasDoubleClick(event: React.MouseEvent): ScreenPoint | null {
  const target = event.target as Element | null;
  if (!target?.classList.contains("react-flow__pane")) return null;
  return { x: event.clientX, y: event.clientY };
}

/**
 * 在画布上双击空白处弹出的那个**可搜索的添加单子**(工作流:节点;画板:格子)。选一项,东西就落在双击的地方。
 *
 * 和工具栏上「添加」是同一份单子、同一个下拉(SearchableSelect),只是锚点换成双击的那一点:一个看不见的、钉在那一点的
 * 零尺寸锚。`at` 为 null 时收起。
 */
export function CanvasPointPicker({
  at,
  options,
  searchPlaceholder,
  onPick,
  onClose,
}: {
  at: ScreenPoint | null;
  options: React.ComponentProps<typeof SearchableSelect>["options"];
  searchPlaceholder: string;
  onPick: (value: string) => void;
  onClose: () => void;
}) {
  // 点浮层**外面**(画布空白)关掉:走 ui 层的全局兜底(见 canvasBlankDismiss)——
  // React Flow 画布会吞掉 Radix「点外部关闭」所依赖的事件,所有 ui 浮层一份兜底修齐,
  // 这里不再单挂监听。
  return (
    <SearchableSelect
      //: 每个双击点一份单子。单子开着时在别处再双击,锚挪了位置,可弹层不会跟着重算(零尺寸的锚动了,定位库察觉不到)
      //: —— 单子会留在上一个点。换一个点就换一份,弹层从新锚重新定位。
      key={at ? `${at.x},${at.y}` : "closed"}
      value=""
      open={at !== null}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      onValueChange={onPick}
      options={options}
      searchPlaceholder={searchPlaceholder}
      trigger={
        <span
          aria-hidden
          data-canvas-point-picker=""
          className="pointer-events-none fixed size-0"
          style={{ left: at?.x ?? 0, top: at?.y ?? 0 }}
        />
      }
    />
  );
}
