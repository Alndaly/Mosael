import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { getModelLibrary } from "@/api/client";
import { previewPick, useModelPreviewSettings } from "@/components/generation/modelPreviewSettings";

/**
 * 一个连接的模型库(模型库弹窗、生成表单里选模型的下拉、工作台的模型库面板读同一份)。
 *
 * 查询键带着「别处的示例图挑哪一张」(见 previewPick):挑法跟着 NSFW 那组设置走,换了挑法,预览图从哪来、NSFW 的判断
 * 都要按新的那张重说一遍。键的前两段(`["model-library", 连接]`)不变 —— 下完一个模型、标了 NSFW 之后按前缀作废。
 */
export function modelLibraryKey(instanceId: string, pick: "safest" | "cover") {
  return ["model-library", instanceId, pick] as const;
}

export function useModelLibrary(instanceId: string, options: { enabled?: boolean; staleTime?: number; retry?: boolean } = {}) {
  const [settings] = useModelPreviewSettings();
  const pick = previewPick(settings);
  const query = useQuery({
    queryKey: modelLibraryKey(instanceId, pick),
    queryFn: () => getModelLibrary(instanceId, pick),
    //: 换了挑法时先留着上一份(卡片照旧在),新的一份到了再换 —— 不让整个模型库闪成「正在读」
    placeholderData: keepPreviousData,
    ...options,
  });
  return { ...query, pick, queryKey: modelLibraryKey(instanceId, pick) };
}
