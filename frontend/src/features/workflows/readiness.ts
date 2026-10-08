/**
 * 一张工作流**现在能不能跑**:编辑器的运行键 / ⌘Enter 和列表卡片上的「运行」读的是同一个判据。
 *
 * 此前只有编辑器会判:列表卡片的「运行」直接发请求,缺必填、连接被删的图照样排进队列,
 * 跑到那一步才失败 —— 而同一张图在编辑器里运行键是灰的。判据本身在 analyze(纯函数),
 * 这里只管「它要的那两份清单从哪来」:编辑器挂着订阅(useWorkflowAnalysis),列表在点下去的
 * 那一刻取一次(analyzeWorkflowNow)。两条路喂给 analyze 的上下文由 contextOf 一处拼。
 */
import React from "react";
import { useQuery, type QueryClient } from "@tanstack/react-query";

import { listProviderProfiles, type GenerationOption, type ProviderProfile, type WorkflowGraph } from "@/api/client";
import { providerKeys } from "@/api/queryKeys";
import { GENERATION_KINDS, promptMode } from "@/lib/generationCapabilities";
import { fetchGenerationOptions, useGenerationOptions } from "@/lib/generationOptions";
import { analyzeWorkflow, type Analysis, type AnalyzeContext, type RegistryLike } from "@/features/workflows/analyze";
import { chatProfileIds, generationVendors } from "@/features/workflows/bindingReadiness";
import { bodyKey } from "@/features/workflows/scope";

/** AI 生成节点的配置指的是清单里哪一个模型。连接身份随模型一起存,同一 vendor/model 可以在多条连接上。 */
export function generationModelOf(models: GenerationOption[], config: Record<string, unknown>): GenerationOption | null {
  return (
    models.find(
      (item) =>
        item.provider === config.provider &&
        item.model === config.model &&
        item.kind === config.kind &&
        (!config.provider_profile_id || item.provider_profile_id === config.provider_profile_id),
    ) ?? null
  );
}

/**
 * 这张图要不要看连接清单 / 生成模型清单 —— 没有对应节点就不去拉。
 *
 * **各层的体一起看。** 此前只看主流程:大模型节点只住在循环体里时连接清单不拉,analyze 却把
 * 「没拉」当成「一条连接都没有」,于是体里好好的大模型节点被报成「连接已删除」,运行键被它挡住。
 */
export function readinessNeeds(graph: WorkflowGraph, registry: RegistryLike): { chat: boolean; generation: boolean } {
  const needs = { chat: false, generation: false };
  const walk = (layer: WorkflowGraph) => {
    for (const node of layer.nodes) {
      if (node.type === "llm") needs.chat = true;
      if (node.type === "ai_generate") needs.generation = true;
      const key = bodyKey(registry, node.type);
      const body = key ? (node.config as Record<string, unknown> | undefined)?.[key] : undefined;
      if (body && typeof body === "object" && Array.isArray((body as WorkflowGraph).nodes)) walk(body as WorkflowGraph);
    }
  };
  walk(graph);
  return needs;
}

/** 喂给 analyze 的上下文。清单是 undefined = 还没拿到:那一类绑定先不判,免得「没拉」被读成「没有」。 */
function contextOf(
  needs: { chat: boolean; generation: boolean },
  profiles: ProviderProfile[] | undefined,
  models: GenerationOption[] | undefined,
): AnalyzeContext {
  return {
    chatProfileIds: chatProfileIds(profiles ?? []),
    chatProfilesLoaded: !needs.chat || profiles !== undefined,
    generationVendors: generationVendors(models ?? []),
    generationModelsLoaded: !needs.generation || models !== undefined,
    generationPromptMode: (config) => promptMode(generationModelOf(models ?? [], config)),
    generationModelFound: (config) => generationModelOf(models ?? [], config) !== null,
  };
}

/** 编辑器用:挂着两份清单的订阅,清单变了判断跟着变。和检查器共用查询键,自动去重。 */
export function useWorkflowAnalysis(graph: WorkflowGraph, registry: RegistryLike): Analysis {
  const needs = React.useMemo(() => readinessNeeds(graph, registry), [graph, registry]);
  const providers = useQuery({ queryKey: providerKeys.profiles(), queryFn: listProviderProfiles, enabled: needs.chat });
  const models = useGenerationOptions(GENERATION_KINDS, { enabled: needs.generation });
  const profiles = providers.isSuccess ? providers.data : undefined;
  const options = models.loaded ? models.options : undefined;
  return React.useMemo(
    () => analyzeWorkflow(graph, registry, contextOf(needs, profiles, options)),
    [graph, registry, needs, profiles, options],
  );
}

/** 列表用:点「运行」的那一刻把要的清单取齐,再判一次。取不到就抛,由调用方当作运行失败报出来。 */
export async function analyzeWorkflowNow(qc: QueryClient, graph: WorkflowGraph, registry: RegistryLike): Promise<Analysis> {
  const needs = readinessNeeds(graph, registry);
  const [profiles, options] = await Promise.all([
    needs.chat ? qc.fetchQuery({ queryKey: providerKeys.profiles(), queryFn: listProviderProfiles }) : undefined,
    needs.generation ? fetchGenerationOptions(qc, GENERATION_KINDS) : undefined,
  ]);
  return analyzeWorkflow(graph, registry, contextOf(needs, profiles, options));
}
