import type { WorkflowNodeType } from "@/api/client";
import PORTS from "@/api/generated/workflow-node-ports.json";
import { messages, type MessageKey } from "@/app/messages";

/**
 * 测试用的内置节点目录:后端导出的接点快照(api/generated/workflow-node-ports.json,backend/scripts/export_openapi.py
 * 生成,后端测试守它的新鲜度)→ 某种界面语言下的注册表。节点目录只在后端,前端测试不另抄一份。
 */

export type CatalogLocale = "zh" | "en";

type Localized = Record<CatalogLocale, string>;

interface PortSnapshot {
  type: string;
  config: Record<string, { label: Localized } & Record<string, unknown>>;
  outputs: string[];
  output_labels: Record<string, Localized>;
  port_maps?: Record<string, Record<string, string>>;
  body_scope?: Record<string, string[]>;
}

export const SNAPSHOT = PORTS as unknown as PortSnapshot[];

export function builtinNodeCatalog(locale: CatalogLocale): Map<string, WorkflowNodeType> {
  return new Map(
    SNAPSHOT.map((one) => [
      one.type,
      {
        type: one.type,
        label: one.type,
        description: "",
        category: "",
        config: Object.fromEntries(Object.entries(one.config).map(([key, spec]) => [key, { ...spec, label: spec.label[locale] }])),
        outputs: one.outputs,
        output_types: {},
        output_labels: Object.fromEntries(Object.entries(one.output_labels).map(([key, label]) => [key, label[locale]])),
        port_maps: one.port_maps ?? {},
        body_scope: one.body_scope ?? {},
        plugin_name: "",
        tool_name: "",
      } satisfies WorkflowNodeType,
    ]),
  );
}

/** 这种界面语言的文案表(真的那一份,不是把 key 原样还回来的替身)。 */
export function uiText(locale: CatalogLocale): (key: MessageKey) => string {
  const table = messages[locale === "zh" ? "zh-CN" : "en-US"];
  return (key) => table[key];
}
