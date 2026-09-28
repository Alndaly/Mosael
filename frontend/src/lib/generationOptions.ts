import { useQueries, type QueryClient } from "@tanstack/react-query";

import { listGenerationOptions, type GenerationOption } from "@/api/domains/generation";
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

/** 命令式的那一份(点「运行」的那一刻把清单取齐):同样的键,有缓存就用缓存。 */
export async function fetchGenerationOptions(qc: QueryClient, kinds: readonly string[]): Promise<GenerationOption[]> {
  const lists = await Promise.all(
    kinds.map((kind) => qc.fetchQuery({ queryKey: generationKeys.options(kind), queryFn: () => listGenerationOptions(kind) })),
  );
  return lists.flat();
}
