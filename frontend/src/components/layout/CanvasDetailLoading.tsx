import { Skeleton } from "@/components/ui/skeleton";

/**
 * 已知要回到某张画布、但详情依赖仍在恢复时的首屏。
 *
 * 这里故意保持详情页的「整张画布 + 左上身份胶囊」轮廓；如果复用列表骨架，刷新详情页时
 * 会先让用户看见上一层入口，再突然跳回画布，视觉上等于发生了一次错误导航。
 */
export function CanvasDetailLoading({ testId }: { testId: string }) {
  return (
    <div className="h-full min-h-0 p-2" data-testid={testId} aria-busy="true">
      <div className="relative h-full min-h-0 overflow-hidden rounded-lg border border-border bg-background">
        <div className="absolute left-2 top-2 inline-flex h-10 items-center gap-2 rounded-full border border-border bg-popover/90 px-2 shadow-[var(--shadow-panel)] backdrop-blur-xl">
          <Skeleton className="size-7 shrink-0 rounded-full" />
          <Skeleton className="h-3.5 w-28 rounded-full" />
        </div>
      </div>
    </div>
  );
}
