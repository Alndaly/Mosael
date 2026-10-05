import React from "react";

import type { WorkflowGraph } from "@/api/client";
import { useI18n } from "@/app/preferences";
import type { RegistryLike } from "@/features/workflows/analyze";
import { workflowPortNamer, type PortNamer, type PortRegistry } from "@/features/workflows/portNames";
import { generationModelOf, readinessNeeds } from "@/features/workflows/readiness";
import { GENERATION_KINDS } from "@/lib/generationCapabilities";
import { useGenerationOptions } from "@/lib/generationOptions";

/**
 * 画布上的接点按界面语言取名(见 portNames)。生成节点的参数名要看它选的那个模型 —— 图里有生成节点才去拉模型清单,
 * 和就绪检查、检查器共用同一份缓存(generationOptions)。清单没到时,宿主认得的参数照样有名字。
 */
export function useWorkflowPortNamer(graph: WorkflowGraph, registry: RegistryLike & PortRegistry): PortNamer {
  const t = useI18n();
  const needs = React.useMemo(() => readinessNeeds(graph, registry), [graph, registry]);
  const models = useGenerationOptions(GENERATION_KINDS, { enabled: needs.generation });
  return React.useMemo(
    () => workflowPortNamer({ registry, t, generationModel: (config) => generationModelOf(models.options, config) }),
    [registry, t, models.options],
  );
}
