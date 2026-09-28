import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

/** 宿主的一项能力用哪一家(ADR 0031 §5):候选、我定的、不定时会用的。 */
export type CapabilityChoices = components["schemas"]["CapabilityChoicesOut"];

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
