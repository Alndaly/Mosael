import type { ModelFile, ModelLibrary } from "@/api/client";
import { modelBaseName } from "@/components/generation/ModelThumb";

/**
 * 模型库列表那一页「看哪些、按什么顺序」的纯函数:目录怎么排、底模有哪些、筛和排。界面(ModelLibrary)只管摆。
 */

type ModelLibraryFolder = NonNullable<ModelLibrary["folders"]>[number];

/** 左栏的「全部」和两个特殊项。目录名不会长这样(ComfyUI 的目录名是 `loras` 这种)。 */
export const ALL_FOLDERS = "__all__";
export const MISSING_VIEW = "__missing__";
export const DOWNLOADS_VIEW = "__downloads__";
/** 认不出底模的那一类(筛选里叫「认不出底模」)。 */
export const UNKNOWN_FAMILY = "__unknown__";

export const SORTS = ["name", "size", "modified"] as const;
export type LibrarySort = (typeof SORTS)[number];

/** 显示方式:大卡片(看预览)、小卡片(一屏多看几张)、列表(扫文件名、大小、时间)。 */
export const DENSITIES = ["large", "small", "list"] as const;
export type LibraryDensity = (typeof DENSITIES)[number];

/** 左栏的目录:有文件的才列,多的在前;一样多按名字。 */
export function folderEntries(folders: readonly ModelLibraryFolder[]): ModelLibraryFolder[] {
  return folders.filter((one) => one.count > 0).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

export const familyOf = (model: Pick<ModelFile, "family">) => model.family || UNKNOWN_FAMILY;

/** 这一批文件里有哪几种底模、各几个:多的在前,认不出的排最后。 */
export function familyCounts(models: readonly ModelFile[]): [string, number][] {
  const counts = new Map<string, number>();
  for (const model of models) counts.set(familyOf(model), (counts.get(familyOf(model)) ?? 0) + 1);
  return [...counts.entries()].sort(
    (a, b) => Number(a[0] === UNKNOWN_FAMILY) - Number(b[0] === UNKNOWN_FAMILY) || b[1] - a[1] || a[0].localeCompare(b[0]),
  );
}

export function inFolder(models: readonly ModelFile[], folder: string): ModelFile[] {
  return folder === ALL_FOLDERS ? [...models] : models.filter((model) => model.folder === folder);
}

/** 按底模(勾了几种就是其中任一)和搜索词筛。搜索看文件名、标题、底模和触发词。 */
export function filterModels(models: readonly ModelFile[], { families, query }: { families: readonly string[]; query: string }): ModelFile[] {
  const wanted = new Set(families);
  const needle = query.trim().toLowerCase();
  return models.filter((model) => {
    if (wanted.size > 0 && !wanted.has(familyOf(model))) return false;
    if (!needle) return true;
    return `${model.name} ${model.title ?? ""} ${model.family ?? ""} ${(model.triggers ?? []).join(" ")}`.toLowerCase().includes(needle);
  });
}

const byName = (a: ModelFile, b: ModelFile) =>
  modelBaseName(a.name).localeCompare(modelBaseName(b.name), undefined, { numeric: true, sensitivity: "base" });

/** 名字按自然顺序(`v2` 在 `v10` 前面);大小、改动时间大的 / 新的在前,一样的按名字。 */
export function sortModels(models: readonly ModelFile[], sort: LibrarySort): ModelFile[] {
  const out = [...models];
  if (sort === "size") return out.sort((a, b) => (b.size ?? -1) - (a.size ?? -1) || byName(a, b));
  if (sort === "modified") return out.sort((a, b) => (b.modified ?? -1) - (a.modified ?? -1) || byName(a, b));
  return out.sort(byName);
}
