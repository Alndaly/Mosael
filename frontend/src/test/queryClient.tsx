import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

/**
 * `render(ui, { wrapper: WithQueryClient })`:给只是**顺带**用到 React Query 的组件一个干净的缓存。
 * 每次渲染一个新的 `QueryClient`、不重试 —— 测试之间不共享缓存,失败也不拖时间。
 */
export function WithQueryClient({ children }: { children: React.ReactNode }) {
  const [client] = React.useState(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
