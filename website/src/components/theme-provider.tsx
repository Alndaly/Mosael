"use client";

import { ThemeProvider as NextThemeProvider } from "next-themes";

/**
 * 深浅色。应用本身有两套主题,官网只做一套会显得是两个产品。
 *
 * `attribute="class"` 对应 globals.css 里的 `@custom-variant dark (&:is(.dark *))`;
 * next-themes 在 <head> 里插一段同步脚本,在首帧之前就把 class 定下来 —— 否则深色用户
 * 每次进站都会先被闪一下白。这也是 <html> 上要 suppressHydrationWarning 的原因。
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <NextThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      {children}
    </NextThemeProvider>
  );
}
