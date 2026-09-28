import type { GenerationOption } from "@/api/client";
import type { components } from "@/api/generated/schema";

/**
 * 节点绑定的服务「配没配好」—— 就绪清单(analyze 的 AnalyzeContext)和节点检查器的提醒**都从这里取**,
 * analyze 只接收这里算出的集合,不自己翻连接或模型清单。
 *
 * 两类节点的判据来源不同,各看各的那份清单:
 * - LLM 节点看连接(`/api/settings/providers`):运行时直接拿那条连接去对话。
 * - 生成节点看可用的生成模型(`/api/generation/options`):后端只列启用连接下启用的模型,
 *   AI 工作台判「没配置」看的就是它。此前这里看连接的 enabled + capability_ids,连接开着而模型全停了时,
 *   工作流说「配好了」、AI 工作台说「没配置」—— 同一件事两个结论。
 */

/** LLM 节点判定要看的那几项连接字段。 */
export type ChatProfileLike = Pick<
  components["schemas"]["ProviderProfileOut"],
  "id" | "enabled" | "auth_type" | "oauth_linked" | "base_url"
>;

/** 自动化(LLM 节点)能不能用这条连接:运行时走直连 API key,或不带工具的 OAuth 网关适配器。 */
function supportsAutomationChat(profile: ChatProfileLike): boolean {
  if (!profile.enabled) return false;
  return profile.auth_type === "oauth" ? profile.oauth_linked : Boolean(profile.base_url?.trim());
}

/** LLM 节点能用的连接 id。 */
export function chatProfileIds(profiles: readonly ChatProfileLike[]): Set<string> {
  return new Set(profiles.filter(supportsAutomationChat).map((profile) => profile.id));
}

/** 有可用生成模型的服务商(vendor)。与 AI 工作台同源:都是后端给的那份生成模型清单。 */
export function generationVendors(models: readonly Pick<GenerationOption, "provider">[]): Set<string> {
  return new Set(models.map((model) => model.provider));
}
