import { LoadingState } from "./LoadingState";

/**
 * Restore a saved canvas in place: the loading surface has the same full-bleed
 * bounds and toolbar inset as the editor, without flashing a framed list page.
 *
 * 这里此前还在左上角摆一块玻璃条(骨架图标 + 骨架标题)——那是「画布自己报名字」那个年代的东西。
 * 名字现在在页头(分级面包屑)里,画布上再摆一个占位就是同一个信息两处;它又只在载入时闪一下,
 * 看着像旧版残留。载入这件事由 LoadingState 说。
 */
export function CanvasDetailLoading({ testId }: { testId: string }) {
  return (
    <div
      className="relative h-full min-h-0 w-full overflow-hidden bg-background"
      data-testid={testId}
      aria-busy="true"
    >
      <LoadingState />
    </div>
  );
}
