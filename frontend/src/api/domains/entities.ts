import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

/**
 * 资产库(ADR 0027):人物 / 场景 / 道具。和「素材」(一个文件)不是一回事 —— 一个资产是「一个有名字的东西」,
 * 参考图是素材库里的素材,这里只引用它们。
 */
export type EntityKind = "character" | "location" | "prop";
export const ENTITY_KINDS: readonly EntityKind[] = ["character", "location", "prop"];

export type EntitySummary = Omit<components["schemas"]["EntitySummaryOut"], "kind"> & { kind: EntityKind };
export type Entity = Omit<components["schemas"]["EntityOut"], "kind" | "variants"> & { kind: EntityKind; variants: EntitySummary[] };
export type EntityReference = components["schemas"]["EntityReferenceOut"];
export type EntityCatalog = components["schemas"]["EntityCatalogOut"];
export type EntityUsage = components["schemas"]["EntityUsageOut"];
export type AssetEntity = Omit<components["schemas"]["AssetEntityOut"], "kind"> & { kind: EntityKind };

/** 一次生成里 `@` 到的一个资产挂了哪几张参考图(后端 domain/entities/mentions 的回执,存在 `request.entities`)。 */
export interface EntityAttachReceipt {
  id: string;
  name: string;
  kind: EntityKind;
  attached: string[];
  dropped: string[];
  /** `limit` / `no_reference_role` / `unknown_limits` / `exclusive` / `subject_too_few` / `prompt_skipped` */
  notes: string[];
}

export type EntityPatch = components["schemas"]["EntityUpdate"];

export const getEntityCatalog = () => api<EntityCatalog>("/api/entities/catalog");

export function listEntities(
  workspaceId: string,
  filters: { kind?: EntityKind | ""; tag?: string; q?: string; parentId?: string; includeVariants?: boolean } = {},
): Promise<EntitySummary[]> {
  const params = new URLSearchParams({ workspace_id: workspaceId });
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.tag) params.set("tag", filters.tag);
  if (filters.q) params.set("q", filters.q);
  if (filters.parentId) params.set("parent_id", filters.parentId);
  if (filters.includeVariants) params.set("include_variants", "true");
  return api<EntitySummary[]>(`/api/entities?${params.toString()}`);
}

export const getEntity = (id: string) => api<Entity>(`/api/entities/${encodeURIComponent(id)}`);

export const createEntity = (body: {
  workspace_id: string;
  kind: EntityKind;
  name: string;
  description?: string;
  prompt?: string;
  tags?: string[];
  parent_id?: string | null;
}) => api<Entity>("/api/entities", { method: "POST", body: JSON.stringify(body) });

export const updateEntity = (id: string, patch: EntityPatch) =>
  api<Entity>(`/api/entities/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(patch) });

export const deleteEntity = (id: string, withVariants = false) =>
  api<void>(`/api/entities/${encodeURIComponent(id)}${withVariants ? "?with_variants=true" : ""}`, { method: "DELETE" });

export const createVariant = (id: string, body: { name: string; prompt?: string; description?: string }) =>
  api<Entity>(`/api/entities/${encodeURIComponent(id)}/variants`, { method: "POST", body: JSON.stringify(body) });

export const dismissLostReferences = (id: string) =>
  api<Entity>(`/api/entities/${encodeURIComponent(id)}/lost-references`, { method: "DELETE" });

export const addEntityReference = (id: string, body: { asset_id: string; role?: string; cover?: boolean }) =>
  api<Entity>(`/api/entities/${encodeURIComponent(id)}/references`, { method: "POST", body: JSON.stringify(body) });

export const setEntityReferenceRole = (id: string, assetId: string, role: string) =>
  api<Entity>(`/api/entities/${encodeURIComponent(id)}/references/${encodeURIComponent(assetId)}`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });

export const removeEntityReference = (id: string, assetId: string) =>
  api<Entity>(`/api/entities/${encodeURIComponent(id)}/references/${encodeURIComponent(assetId)}`, { method: "DELETE" });

export const reorderEntityReferences = (id: string, assetIds: string[]) =>
  api<Entity>(`/api/entities/${encodeURIComponent(id)}/references/order`, {
    method: "PUT",
    body: JSON.stringify({ asset_ids: assetIds }),
  });

/** 「补全多角度」「生成表情」的请求(和画板上资产格的那两项能力同一件事,后端 domain/entities/drawing)。 */
export type EntityDrawRequest = components["schemas"]["EntityDrawRequest"];

/** 照参考图再画几张,画成的挂回来。说不通的(没图、模型不收参考图、角度都齐了)当场 422;说得通回那个任务。 */
export const drawEntity = (id: string, body: EntityDrawRequest) =>
  api<components["schemas"]["JobOut"]>(`/api/entities/${encodeURIComponent(id)}/draw`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getEntityUsage = (id: string) => api<EntityUsage>(`/api/entities/${encodeURIComponent(id)}/usage`);

export const listAssetEntities = (assetId: string) =>
  api<AssetEntity[]>(`/api/assets/${encodeURIComponent(assetId)}/entities`);

/** 缓存键:取数可以细,失效用最短的那个前缀(同 api/queryKeys 的约定)。 */
export const entityKeys = {
  all: (workspaceId: string) => ["entities", workspaceId] as const,
  list: (workspaceId: string, filters: Record<string, unknown> = {}) => ["entities", workspaceId, "list", filters] as const,
  detail: (workspaceId: string, id: string) => ["entities", workspaceId, "detail", id] as const,
  usage: (workspaceId: string, id: string) => ["entities", workspaceId, "usage", id] as const,
  ofAsset: (workspaceId: string, assetId: string) => ["entities", workspaceId, "asset", assetId] as const,
  catalog: () => ["entity-catalog"] as const,
};

/** 这次生成的回执(`generation.request.entities`)—— 读的时候不信任形状,认不出的项丢掉。 */
export function entityReceipt(request: Record<string, unknown> | undefined | null): EntityAttachReceipt[] {
  const rows = request?.entities;
  if (!Array.isArray(rows)) return [];
  return rows.filter((row): row is EntityAttachReceipt => Boolean(row && typeof row === "object" && "id" in row));
}
