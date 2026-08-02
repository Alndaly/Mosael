"use client";

import * as React from "react";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";

/**
 * 深浅色开关。
 *
 * 只在 light / dark 之间切,不给"跟随系统"单独一档 —— 三态开关要按两次才回到原处,
 * 而访客对官网的期待就是"点一下换个样子"。初值仍然跟随系统(ThemeProvider 那侧)。
 *
 * 挂载前渲染一个占位:服务端不知道用户的主题,直接画图标会 hydration 不一致,
 * 而按尺寸留白至少不会让 header 在首帧抖一下。
 */
export function ThemeToggle({ label }: { label: string }) {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);

  const isDark = resolvedTheme === "dark";
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={label}
      title={label}
      onClick={() => setTheme(isDark ? "light" : "dark")}
    >
      {mounted ? isDark ? <Sun /> : <Moon /> : <span className="size-4" />}
    </Button>
  );
}
