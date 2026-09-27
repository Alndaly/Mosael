"use client";

import { Check, Share2 } from "lucide-react";

import { BUTTON, useCopy } from "@/components/community/ui";
import { cn } from "@/lib/utils";

/**
 * 分享 / 复制链接。手机上有系统分享面板就用它(发给微信、存进备忘录),没有就复制到剪贴板。
 */
export function ShareButton({ title, label, copiedLabel }: { title: string; label: string; copiedLabel: string }) {
  const [copied, copy] = useCopy();
  const share = async () => {
    const url = window.location.href.split("#")[0];
    if (typeof navigator.share === "function" && window.matchMedia("(pointer: coarse)").matches) {
      try {
        await navigator.share({ title, url });
        return;
      } catch {
        // 用户关掉了分享面板:退回复制。
      }
    }
    copy(url);
  };
  return (
    <button type="button" onClick={() => void share()} className={cn(BUTTON.secondary, "min-h-9 px-4")}>
      {copied ? <Check className="size-4" aria-hidden /> : <Share2 className="size-4" aria-hidden />}
      {copied ? copiedLabel : label}
    </button>
  );
}
