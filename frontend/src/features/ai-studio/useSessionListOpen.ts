import React from "react";

const KEY = "mosael.ai-session-list-open";

/** AI Studio 左侧会话列表的展开状态:默认开,记在这台机器上。 */
export function useSessionListOpen(): readonly [boolean, React.Dispatch<React.SetStateAction<boolean>>] {
  const [open, setOpen] = React.useState(() => {
    try {
      return window.localStorage.getItem(KEY) !== "0";
    } catch {
      return true;
    }
  });
  React.useEffect(() => {
    try {
      window.localStorage.setItem(KEY, open ? "1" : "0");
    } catch {
      // 记不住就按本次窗口的状态用,不挡功能。
    }
  }, [open]);
  return [open, setOpen] as const;
}
