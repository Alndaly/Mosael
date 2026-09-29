import { useQuery } from "@tanstack/react-query";

import { listCapabilityTerms, type CapabilityTerm } from "@/api/domains/capabilities";
import { capabilityKeys } from "@/api/queryKeys";

/**
 * 插件能替 Mosael 做的那几类事(清单里的 `provides`)叫什么、装上之后用在哪。
 *
 * 词表只有后端那一份(能力表 + 生成、工具清单)。此前这里手写了两项(素材外链、文档解析),后来的降噪、转写、
 * 翻译、配音在市场里只显示原词 —— 每加一项能力就得记得回来补一句,而没人记得。认不出的词照原样显示。
 */
export function useCapabilityTerms(): { terms: CapabilityTerm[]; termOf: (name: string) => CapabilityTerm | undefined; labelOf: (name: string) => string } {
  const query = useQuery({ queryKey: capabilityKeys.terms(), queryFn: listCapabilityTerms, staleTime: Infinity });
  const terms = query.data ?? [];
  const termOf = (name: string) => terms.find((term) => term.name === name);
  return { terms, termOf, labelOf: (name) => termOf(name)?.label ?? name };
}
