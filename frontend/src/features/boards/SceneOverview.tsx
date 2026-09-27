import { useQuery } from "@tanstack/react-query";
import React from "react";

import { getScene, scenePreviewUrl } from "@/api/client";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * 一个 3D 场景长什么样:整个场景的全景白模,后端渲(和出片参考同一个渲染器,见后端 scenes.scene_overview_image)。
 *
 * 画板上的 3D 场景格和它的面板都画它。此前格子里是一张「导出过的缩略图」,没导出过就是一句「选一个镜头,渲出首尾帧
 * 或运镜视频」—— 刚按文字搭好的场景在格子上什么也看不见(用户截图)。**地址里带修订号**:场景在编辑器里改过,
 * 回到画板时读到新修订,换一张;没改就用浏览器缓存。
 */
export function SceneOverview({
  workspaceId,
  sceneId,
  fallback,
  className,
}: {
  workspaceId: string;
  sceneId: string;
  fallback: React.ReactNode;
  className?: string;
}) {
  const scene = useQuery({ queryKey: ["scene", workspaceId, sceneId], queryFn: () => getScene(workspaceId, sceneId) });
  const src = scene.data ? scenePreviewUrl(workspaceId, sceneId, scene.data.revision) : "";
  const [failed, setFailed] = React.useState<string | null>(null);
  const [loaded, setLoaded] = React.useState<string | null>(null);
  if (scene.isError || (src && failed === src)) return <>{fallback}</>;
  return (
    <div data-scene-overview="" className={cn("relative h-full w-full overflow-hidden", className)}>
      {loaded !== src && <Skeleton surface className="absolute inset-0 h-full w-full rounded-none" />}
      {src && (
        <img
          src={src}
          alt=""
          draggable={false}
          onLoad={() => setLoaded(src)}
          onError={() => setFailed(src)}
          className={cn("h-full w-full object-cover", loaded !== src && "opacity-0")}
        />
      )}
    </div>
  );
}
