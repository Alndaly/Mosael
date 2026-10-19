import { AlertCircle, Check, Loader2, PenLine } from "lucide-react";

import { Hint } from "@/components/ui/tooltip";

import { useNoteStrings } from "./strings";

/** 保存状态的四个取值。图标和说明都按它查表 —— 它们是同一件事的两面,不该各写一遍四分支。 */
export type NoteStatus = "saved" | "saving" | "draft" | "error";
const STATUS_ICON = { saved: Check, saving: Loader2, draft: PenLine, error: AlertCircle } as const;

/**
 * 保存状态:一个图标位。**图形**随状态换(对勾 / 转圈 / 铅笔 / 警示),颜色只是第二层 ——
 * 只靠颜色的话,色弱的人分不出「已保存」和「有改动」。
 *
 * - 名字在悬停说明里,不再摆一行字把工具栏撑开;失败那一条还说清可以重试(提示带里就有「重试保存」);
 * - 读屏走 `role="status"` 的活区:图标 `aria-hidden`,里面留一份 `sr-only` 的字给朗读 ——
 *   活区里的字不跟着换的话,状态变了也不会被念到。
 */
export function NoteSaveStatus({ status }: { status: NoteStatus }) {
  const s = useNoteStrings();
  const Icon = STATUS_ICON[status];
  const hint = s[status];
  return (
    <Hint label={hint}>
      <span className="note-status" role="status" aria-live="polite" data-slot="save-status" data-state={status}>
        <Icon size={12} className={status === "saving" ? "animate-mosael-spin" : undefined} aria-hidden="true" />
        <span className="sr-only">{hint}</span>
      </span>
    </Hint>
  );
}
