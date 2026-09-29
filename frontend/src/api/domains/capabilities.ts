import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

/** 宿主的一项能力用哪一家(ADR 0031 §5):候选、我定的、不定时会用的。 */
export type CapabilityChoices = components["schemas"]["CapabilityChoicesOut"];

/** 插件清单 `provides` 里能写的一项:叫什么、装上之后用在哪(ADR 0032 §4)。 */
export type CapabilityTerm = components["schemas"]["CapabilityTermOut"];

/** 词表由后端给(能力表 + 生成、工具清单):插件市场按它筛,插件页照它说。前端不自己写能力的名字。 */
export function listCapabilityTerms(): Promise<CapabilityTerm[]> {
  return api<CapabilityTerm[]>("/api/plugins/capabilities");
}

export function listCapabilityChoices(): Promise<CapabilityChoices[]> {
  return api<CapabilityChoices[]>("/api/settings/capabilities");
}

/** 定下(或清掉,`null` / 内置实现的 id)这项能力的默认提供方。 */
export function setCapabilityDefault(capability: string, providerId: string | null): Promise<CapabilityChoices> {
  return api<CapabilityChoices>(`/api/settings/capabilities/${capability}`, {
    method: "PUT",
    body: JSON.stringify({ provider_id: providerId }),
  });
}
