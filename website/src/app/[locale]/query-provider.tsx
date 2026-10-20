"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { createQueryClient } from "@/lib/query-client";

/**
 * TanStack Query 的 client wrapper。
 *
 * `[locale]/layout.tsx` 是 **server component**(`generateStaticParams` / `metadata` 都在那儿),
 * 所以 Provider 不能直接写进去 —— 单独一个 `"use client"` 壳,Server Component 渲染它、
 * 它把 children 原样接住。挂在 [locale] 根布局意味着 `(site)` 与 `(auth)` 两组页面共用
 * 同一份缓存:登录 / 退出发生在 `(auth)`,站头在 `(site)`,正是靠这一点把 viewer 串起来。
 *
 * QueryClient 用 `useState` 的惰性初始化**每个浏览器会话建一份**,不在模块顶层共享 ——
 * 否则 SSR 时多个请求会串缓存,一处「已登录」会漏给另一个访客。
 */
export function QueryProvider({ children }: { children: ReactNode }) {
  const [queryClient] = useState(createQueryClient);
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
