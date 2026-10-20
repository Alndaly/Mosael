"use client";

import { useEffect, useState } from "react";

/**
 * 重发验证码的本地倒计时。
 *
 * **服务端才是最终裁决**(60 秒冷却 + 每小时上限);这里只负责让按钮在 60 秒内别催人,
 * 并把"还剩几秒"变成一个读屏也能听到的文字标签。秒数和服务端常量保持一致。
 */
export const RESEND_COOLDOWN_SECONDS = 60;

export function useResendCountdown(seconds: number = RESEND_COOLDOWN_SECONDS) {
  const [remaining, setRemaining] = useState(0);

  useEffect(() => {
    if (remaining <= 0) return;
    const timer = setTimeout(() => setRemaining((value) => Math.max(0, value - 1)), 1000);
    return () => clearTimeout(timer);
  }, [remaining]);

  return {
    remaining,
    start: () => setRemaining(seconds),
    reset: () => setRemaining(0),
  };
}
