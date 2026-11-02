/** 参考库(ADR 0091 §3):插件提供的只读外部图集,单条取用后才进工作区。 */
import { api } from "@/api/transport";

export type ReferenceCollection = {
  id: string;
  kind: "pose" | "costume";
  name: Record<string, string>;
  count: number;
  filters: { key: string; label: string; values: { value: string; label: string }[] }[];
};

export type ReferenceView = { role: string; thumbnail: string; original: string };

export type ReferenceItem = {
  id: string;
  collection: string;
  kind: "pose" | "costume";
  name: Record<string, string>;
  tags: string[];
  thumbnail: string;
  views: ReferenceView[];
  nsfw: boolean;
  provenance: { author: string; url: string; license: string };
};

export type ReferenceConnection = { id: string; name: string };

export type ReferencePage = { items: ReferenceItem[]; next_cursor: string };

export type ReferenceUseResult = {
  asset_id: string;
  entity_id: string;
  item: ReferenceItem;
  provenance: Record<string, unknown>;
};

export const listReferenceConnections = () => api<ReferenceConnection[]>("/api/reference-library/connections");

export const listReferenceCollections = (instanceId: string) =>
  api<ReferenceCollection[]>(`/api/reference-library/${encodeURIComponent(instanceId)}/collections`);

export function searchReferenceItems(
  instanceId: string,
  query: { collection?: string; q?: string; filters?: Record<string, string>; cursor?: string; limit?: number } = {},
): Promise<ReferencePage> {
  const params = new URLSearchParams();
  if (query.collection) params.set("collection", query.collection);
  if (query.q) params.set("q", query.q);
  if (query.cursor) params.set("cursor", query.cursor);
  if (query.limit) params.set("limit", String(query.limit));
  if (query.filters && Object.keys(query.filters).length) params.set("filters", JSON.stringify(query.filters));
  return api<ReferencePage>(`/api/reference-library/${encodeURIComponent(instanceId)}/search?${params.toString()}`);
}

export const getReferenceItem = (instanceId: string, itemId: string, collection = "") => {
  const params = new URLSearchParams({ item_id: itemId });
  if (collection) params.set("collection", collection);
  return api<ReferenceItem>(`/api/reference-library/${encodeURIComponent(instanceId)}/item?${params.toString()}`);
};

export const ingestReferenceItem = (
  instanceId: string,
  //: `role`:「用作素材」取哪个视角(空 = 第一张);「存为资产」每个视角各取一张,不看它。
  body: { workspace_id: string; item_id: string; collection?: string; role?: string; save_entity?: boolean },
) => api<ReferenceUseResult>(`/api/reference-library/${encodeURIComponent(instanceId)}/use`, {
  method: "POST",
  body: JSON.stringify(body),
});
