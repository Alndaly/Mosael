import React from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import { separateAssetAudio } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { DenoiseDialog } from "@/features/media/DenoiseDialog";

/**
 * 素材层面的两个声音处理:**人声与背景音分离**(ADR-0016)和**降噪**(ADR-0017)。
 *
 * 两者都处理整份素材、产出新素材进素材库,原素材不动 —— 所以入口在素材的菜单里(素材库、剪辑页素材池),
 * 不在时间线片段的菜单里。菜单项给不给由调用方按 `kindHasSound(asset.kind)` 决定。
 *
 * - `separate`:排任务,不等结果。长素材在本机要跑十几分钟,完成后两份素材自己出现在素材库里;
 *   没装引擎时后端直接说清楚。
 * - `denoise(assetId)`:要选档位和方式,打开对话框;`denoiseDialog` 由调用方挂在自己的树里。
 */
export function useAssetAudioActions() {
  const t = useI18n();
  const separate = useMutation({
    mutationFn: (assetId: string) => separateAssetAudio(assetId),
    onSuccess: () => toast.success(t("separateAudioQueued")),
    onError: (error: Error) => toast.error(error.message),
  });
  const [denoising, setDenoising] = React.useState<string | null>(null);
  const denoiseDialog = <DenoiseDialog assetId={denoising} onClose={() => setDenoising(null)} />;
  return { separate, denoise: setDenoising, denoiseDialog };
}
