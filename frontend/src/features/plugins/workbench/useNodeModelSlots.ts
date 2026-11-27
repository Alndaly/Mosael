import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { getNodeFolders } from "@/api/client";
import {
  comboInputs,
  modelSlots,
  type ModelSlot,
  type WorkbenchNode,
} from "@/features/plugins/workbench/workbenchLogic";
import type { WorkbenchTarget } from "@/features/plugins/workbench/workbenchSession";

/**
 * 一个选中节点上的模型槽。节点、目录查询和结果只在这里算一次：NodePanel 用它画槽位，
 * ModelsPanel 用它在模型卡上给「填入当前节点」。
 */
export function useNodeModelSlots(target: WorkbenchTarget, node: WorkbenchNode | null) {
  const inputs = useMemo(() => comboInputs(node), [node]);
  const folders = useQuery({
    queryKey: ["comfy-node-folders", target.instanceId, JSON.stringify(inputs)],
    queryFn: () => getNodeFolders(target.instanceId, inputs),
    enabled: inputs.length > 0,
    staleTime: Infinity,
  });
  const slots = useMemo(
    () => modelSlots(node, folders.data?.folders ?? [], folders.data?.encoders ?? []),
    [node, folders.data],
  );
  return {
    inputs,
    slots,
    pending: folders.isPending && inputs.length > 0,
    error: folders.error,
  } satisfies { inputs: typeof inputs; slots: ModelSlot[]; pending: boolean; error: unknown };
}
