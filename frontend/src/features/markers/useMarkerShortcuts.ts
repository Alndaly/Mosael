import React from "react";

import { markerForCombo, type CanvasMarker } from "@/features/markers/markers";
import { comboFromEvent, isTypingTarget } from "@/lib/shortcuts";

/**
 * 按下绑定的键 → 跳到那个标记。
 *
 * 挂在 window 上而不是画布元素上:用户按键的时候焦点常常在右侧检查器、工具条按钮或者干脆
 * 什么都没选中 —— 要求"先点一下画布"就等于要求用户先去猜焦点在哪。
 *
 * 在能打字的地方一律让路(单键绑定必须如此,否则在提示词里打一个 "1" 就被传送走了)。
 */
export function useMarkerShortcuts(
  markers: CanvasMarker[],
  jump: (marker: CanvasMarker) => void,
  enabled = true,
): void {
  // 回调每轮都是新的,但这条监听不该每轮拆装一次(拆装的间隙里按下的键会丢)。
  const latest = React.useRef({ markers, jump });
  latest.current = { markers, jump };

  React.useEffect(() => {
    if (!enabled) return;
    const onKey = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target)) return;
      const combo = comboFromEvent(event);
      if (!combo) return;
      const marker = markerForCombo(latest.current.markers, combo);
      if (!marker) return;
      // 拦下来:绑到 ⌥1 之类的组合上时,浏览器/系统那边也可能有自己的动作。
      event.preventDefault();
      latest.current.jump(marker);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled]);
}
