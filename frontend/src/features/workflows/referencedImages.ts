import type { WorkflowGraph } from "@/api/client";
import type { ConfigSpec } from "@/features/nodeForms/NodeConfigForm";
import { bareRef } from "@/features/nodeForms/refDoc";
import { extractRefs, type RegistryLike } from "@/features/workflows/analyze";

/**
 * **「引用即发送」在界面上的那一半**:提示词(或系统提示词)里 `{{…}}` 引用到的图,运行时会自动和
 * 提示词一起发给模型 —— 维护者:「对这种通过 `@` 引用了图片素材的 LLM 节点,其中的『要模型看的图片』
 * 应该自动同步」。推导在后端(binding.with_referenced_assets,运行时,值到那一刻才知道),这里算出
 * **哪几处引用会成为图片**,交给「要模型看的图片」那一格的控件摆出来:自动来的和手动挑的**分开摆**,
 * 一眼看得出模型为什么会看到它。
 *
 * 只算引用,不算到具体的素材 id:值要到运行时才有(上游可能还没跑)。唯一静态就知道的情形是源节点
 * 本身就是「素材」、而它指的那份素材是写死的 id —— 那时连它是不是图片都判得了(见 AssetGridField)。
 *
 * 「哪几处引用算数」这条线和后端同一条(那儿是 node_types.output_data_type 加一个不是素材的类型集合):
 * 引用的那个输出**不可能**装素材的(`{{llm.text}}`、`{{q.count}}`)不算 —— 那些引用本来就只是文字。
 */

/** 这一格里自动来的一处引用。 */
export interface ReferencedImage {
  /** 存进排除清单(`<那一格>_excluded`)的记号:引用路径(`图.asset_id`,不带花括号)。 */
  path: string;
  /** 静态就知道它指的是哪张素材(源节点是「素材」且写死了 id)时给出来,否则 null。 */
  assetId: string | null;
}

/** 不可能装素材的输出:引用它不会被当成「要模型看的图」(和后端 binding._NOT_ASSETS 同一条)。 */
const NOT_ASSETS = new Set(["text", "number", "json", "sequence", "scene"]);

/**
 * 一张图里,每个声明了 `ref_assets_from` 的配置字段 → 自动并进它的那几处引用(按声明顺序、
 * 引用出现的先后,同一个引用只算一次)。没有自动来的字段不出现在结果里。
 */
export function referencedImages(
  specs: Record<string, ConfigSpec>,
  config: Record<string, unknown>,
  registry: RegistryLike,
  nodes: readonly WorkflowGraph["nodes"][number][],
): Record<string, ReferencedImage[]> {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const found: Record<string, ReferencedImage[]> = {};
  for (const [key, spec] of Object.entries(specs)) {
    const sources = spec?.ref_assets_from;
    if (!Array.isArray(sources)) continue;
    const seen = new Set<string>();
    const refs: ReferencedImage[] = [];
    for (const source of sources) {
      for (const { ref, sourceId } of extractRefs(config[source])) {
        const path = bareRef(ref);
        const output = path.split(".").slice(1).join(".");
        const from = byId.get(sourceId);
        if (!output || !from || seen.has(path)) continue;
        seen.add(path);
        //: 读的是注册表里**原样的**声明值(后端 `output_data_type` 交出来的那一份),不是 outputType 归一化
        //: 之后的那几个 —— 归一化把 `scene` 收成 any,而场景和 text 一样不可能装素材。两边同一个集合。
        const declared = registry.get(from.type)?.output_types?.[output];
        if (typeof declared === "string" && NOT_ASSETS.has(declared)) continue;
        refs.push({ path, assetId: staticAssetId(from, output) });
      }
    }
    if (refs.length > 0) found[key] = refs;
  }
  return found;
}

/** 源节点是「素材」、而它指的是写死的一份素材时,静态就知道这一处引用指向哪一张(判得了它是不是图片)。 */
function staticAssetId(node: WorkflowGraph["nodes"][number], output: string): string | null {
  if (node.type !== "asset" || output !== "asset_id") return null;
  const value = String((node.config ?? {}).asset_id ?? "").trim();
  return value && !value.includes("{{") ? value : null;
}
