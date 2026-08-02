"use client";

import * as React from "react";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

/**
 * 深浅色开关。
 *
 * 只在 light / dark 之间切,不给"跟随系统"单独一档 —— 三态开关要按两次才回到原处,
 * 而访客对官网的期待就是"点一下换个样子"。初值仍然跟随系统(ThemeProvider 那侧)。
 *
 * 挂载前渲染一个等大的空位:服务端不知道用户的主题,直接画图标会 hydration 不一致,
 * 而按尺寸留白至少不会让顶栏在首帧抖一下。
 */
export function ThemeToggle({ label }: { label: string }) {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);

  const isDark = resolvedTheme === "dark";
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className="inline-flex size-9 items-center justify-center border-2 border-ink transition-colors hover:bg-ink hover:text-paper"
    >
      {mounted ? isDark ? <Sun className="size-4" /> : <Moon className="size-4" /> : <span className="size-4" />}
    </button>
  );
}
