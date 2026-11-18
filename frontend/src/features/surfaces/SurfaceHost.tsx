import React from "react";

import { PageBoundary } from "@/app/PageBoundary";
import { PAGE_RENDERERS, type PageContext } from "@/app/pages";
import type { StudioView } from "@/components/layout/navLabels";
import { LoadingState } from "@/components/layout/LoadingState";

/**
 * 页面渲染的唯一出口。
 *
 * App 不再直接访问 `PAGE_RENDERERS`;后续 AI Studio 的侧栏 surface、全屏 surface 和
 * 页面路由都从这里进。这样 surface 的边界(懒加载失败、Suspense、按页面重置错误边界)
 * 只有一份,不会在“主页面”和“侧栏页面”之间分叉。
 */
export function SurfaceHost({
  view,
  context,
  loadingLabel,
}: {
  view: StudioView;
  context: PageContext;
  loadingLabel: string;
}) {
  return (
    <PageBoundary resetKey={view}>
      <React.Suspense fallback={<LoadingState label={loadingLabel} />}>
        {PAGE_RENDERERS[view](context)}
      </React.Suspense>
    </PageBoundary>
  );
}
