import React from "react";
import { useQuery } from "@tanstack/react-query";

import { getAsset } from "@/api/client";
import { assetKeys } from "@/api/queryKeys";
import { AssetPreviewModal } from "@/features/media/AssetPreviewModal";

/**
 * 只有素材 id 的地方也能打开完整素材详情。
 *
 * 画板参考槽、智能体工具结果拿到的通常只是投影(id / kind / name)，而详情弹窗需要完整的
 * media_info。统一在这一层按 id 补齐，调用方不用各自维护一份“先查素材再开弹窗”的状态机。
 */
export function AssetPreviewModalById({ id, onClose }: { id: string | null; onClose: () => void }) {
  const asset = useQuery({
    queryKey: assetKeys.detail(id ?? ""),
    enabled: Boolean(id),
    queryFn: () => getAsset(id!),
  });

  return <AssetPreviewModal asset={id ? asset.data ?? null : null} onClose={onClose} />;
}

/**
 * 「点一下打开这个素材的详情」给没有自己弹窗状态的地方用:返回打开函数和要挂进树里的弹窗。
 *
 * 文档、音频、3D 这些没有灯箱可放的素材,点开就是这张详情(文档是三栏阅读);图和视频照旧走全局灯箱。
 */
export function useAssetPreviewModal() {
  const [id, setId] = React.useState<string | null>(null);
  return {
    openAsset: setId,
    //: 没打开时什么都不挂:一屏几十个气泡各挂一个查询钩子,全花在没人点的东西上。
    modal: id ? <AssetPreviewModalById id={id} onClose={() => setId(null)} /> : null,
  };
}
