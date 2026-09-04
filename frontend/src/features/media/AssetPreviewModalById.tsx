import { useQuery } from "@tanstack/react-query";

import { api, type Asset } from "@/api/client";
import { AssetPreviewModal } from "@/features/media/AssetPreviewModal";

/**
 * 只有素材 id 的地方也能打开完整素材详情。
 *
 * 画板参考槽、智能体工具结果拿到的通常只是投影(id / kind / name)，而详情弹窗需要完整的
 * media_info。统一在这一层按 id 补齐，调用方不用各自维护一份“先查素材再开弹窗”的状态机。
 */
export function AssetPreviewModalById({ id, onClose }: { id: string | null; onClose: () => void }) {
  const asset = useQuery({
    queryKey: ["asset", id],
    enabled: Boolean(id),
    queryFn: () => api<Asset>(`/api/assets/${id}`),
  });

  return <AssetPreviewModal asset={id ? asset.data ?? null : null} onClose={onClose} />;
}
