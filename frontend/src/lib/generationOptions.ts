import { useQueries, type QueryClient } from "@tanstack/react-query";

import { useQuery } from "@tanstack/react-query";

import { listGenerationOptions, listUnavailableModels, type GenerationOption } from "@/api/domains/generation";
import { generationKeys } from "@/api/queryKeys";

/**
 * 生成选项按种类各取一份、合成一张清单。AI 工作台、画板的提示词面板、工作流的检查器和就绪判断用的都是这里,
 * 于是读的是**同一份缓存**(`generationKeys.options(kind)`)。此前三处各拉各的形状 —— 按种类一份、
 * 画板把几种合成一份、工作流把全部合成一份 —— 同一份数据缓存三遍,谁也不和谁共享。
 */
export type GenerationOptions = {
  options: GenerationOption[];
  /** 每一种都取到了。没取到之前别拿空清单下「一个模型都没有」的结论。 */
  loaded: boolean;
  /** 还有一种在取。 */
  pending: boolean;
};

//: 放在模块级:`combine` 是稳定的函数时,结果只在数据变了才换引用。
function combine(results: Array<{ data?: GenerationOption[]; isPending: boolean; isSuccess: boolean }>): GenerationOptions {
  return {
    options: results.flatMap((result) => result.data ?? []),
    loaded: results.every((result) => result.isSuccess),
    pending: results.some((result) => result.isPending),
  };
}

export function useGenerationOptions(kinds: readonly string[], { enabled = true }: { enabled?: boolean } = {}): GenerationOptions {
  return useQueries({
    queries: kinds.map((kind) => ({
      queryKey: generationKeys.options(kind),
      queryFn: () => listGenerationOptions(kind),
      enabled,
    })),
    combine,
  });
}

/**
 * 选着的 (连接, 模型) 不在生成选项里时,插件说过的「现在用不了、为什么」(ComfyUI:那张工作流的表单还是旧格式,到工作流库里升级,
 * ADR 0045 §7);没说过、或者就在选项里,是 null。界面据此在「选择模型」旁边说清楚,不让人以为选择丢了。
 */
export function useUnavailableReason(profileId: string | null | undefined, model: string | null | undefined): string | null {
  const unavailable = useQuery({
    queryKey: generationKeys.unavailable(),
    queryFn: listUnavailableModels,
    enabled: Boolean(profileId && model),
    staleTime: 30_000,
  });
  if (!profileId || !model) return null;
  return unavailable.data?.find((one) => one.provider_profile_id === profileId && one.model === model)?.reason ?? null;
}

/** 命令式的那一份(点「运行」的那一刻把清单取齐):同样的键,有缓存就用缓存。 */
export async function fetchGenerationOptions(qc: QueryClient, kinds: readonly string[]): Promise<GenerationOption[]> {
  const lists = await Promise.all(
    kinds.map((kind) => qc.fetchQuery({ queryKey: generationKeys.options(kind), queryFn: () => listGenerationOptions(kind) })),
  );
  return lists.flat();
}
