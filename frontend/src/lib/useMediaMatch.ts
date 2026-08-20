import React from "react";

/**
 * 一个媒体查询此刻是否命中,并随窗口变化更新。
 *
 * 给「布局由 JS 内联样式决定」的地方用:内联 `gridTemplateColumns` 会**覆盖** class 里的
 * `max-[...]` 响应式回退,所以断点必须搬进 JS 一起判 —— 只写在 class 里的那份会被内联值
 * 悄悄压掉,窄窗口下三栏挤成一团(剪辑页的 useCompact 就是同一件事,这里提成公共的)。
 */
export function useMediaMatch(query: string): boolean {
  return React.useSyncExternalStore(
    (notify) => {
      const media = window.matchMedia(query);
      media.addEventListener("change", notify);
      return () => media.removeEventListener("change", notify);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}
