import { PenLine } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { Messages } from "@/i18n/messages";

/**
 * 还没有 handle 时的那句「先起个名字」。
 *
 * 云端把「没有昵称」当成 409 `identity_required`(不是没登录),所以这里不跳登录页:就在
 * 原地告诉用户还差什么,并给一条去「个人信息」的路。概览和分享列表共用它 —— 没有 handle
 * 就没有 `/users/{handle}/shares` 可读,把统计画成 0 是在说谎。
 */
export function NamePrompt({
  copy,
  onGoToProfile,
  compact = false,
}: {
  copy: Messages["dashboard"];
  onGoToProfile: () => void;
  /** 概览里已经有大卡片时用紧凑版,避免一屏两块同款提示。 */
  compact?: boolean;
}) {
  return (
    <div
      className={
        compact
          ? "flex flex-wrap items-center gap-x-4 gap-y-3 rounded-xl border border-border bg-card px-4 py-3.5"
          : "rounded-xl border border-border bg-card p-5 sm:p-6"
      }
    >
      <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-accent">
        <PenLine className="size-5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <h2 className={compact ? "m-0 text-sm font-semibold" : "m-0 font-display text-lg font-semibold tracking-[-0.02em]"}>
          {copy.noHandleTitle}
        </h2>
        <p className={compact ? "mt-1 mb-0 text-[13px] leading-6 text-muted-foreground" : "mt-2 mb-0 text-sm leading-7 text-muted-foreground"}>
          {copy.noHandleBody}
        </p>
      </div>
      <Button onClick={onGoToProfile} size="sm">
        {copy.goToProfile}
      </Button>
    </div>
  );
}
