import React from "react";

/**
 * 设置组里「这几行一起提交」的那一排按钮(凭据的保存、手动填的令牌的保存)。
 *
 * 内距和行同一刻度、上下对称(px-0.5 py-3);**不画上边线**:它属于上面那几行,不是新的一行。
 */
export function GroupActions({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-2 px-0.5 py-3 !border-t-0">
      <div className="flex shrink-0 items-center gap-2">{children}</div>
    </div>
  );
}
