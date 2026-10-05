import type { ModelFile, ModelLibrary } from "@/api/client";
import type { GenerationOption } from "@/api/domains/generation";
import type { MessageKey } from "@/app/messages";
import { modelBaseName, normModelName } from "@/components/generation/ModelThumb";
import { declaredParameters } from "@/lib/generationCapabilities";

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
/** 「底模」这件事不适用的那一类:文本编码器、放大模型、检测模型……(插件报 `family_source: "not_applicable"`)。 */
export const NOT_APPLICABLE_FAMILY = "__not_applicable__";

export const SORTS = ["name", "size", "modified"] as const;
export type LibrarySort = (typeof SORTS)[number];


/** 左栏的目录:有文件的才列,多的在前;一样多按名字。 */
export function folderEntries(folders: readonly ModelLibraryFolder[]): ModelLibraryFolder[] {
  return folders.filter((one) => one.count > 0).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

type FamilyFields = Pick<ModelFile, "family" | "family_source">;

export const familyOf = (model: FamilyFields) =>
  model.family || (model.family_source === "not_applicable" ? NOT_APPLICABLE_FAMILY : UNKNOWN_FAMILY);

/** 筛选里那两个特殊项的文案;别的就是家族名本身(null)。 */
export function familyLabelKey(value: string): MessageKey | null {
  if (value === UNKNOWN_FAMILY) return "modelLibraryFamilyUnknown";
  if (value === NOT_APPLICABLE_FAMILY) return "modelLibraryFamilyNotApplicable";
  return null;
}

/**
 * 底模旁边那句「凭的是什么」和徽章的轻重:元数据、权重结构写在文件里(`certain`,实色),文件名是猜的(淡色);
 * 不适用的说为什么不适用;认不出的没有。
 */
export function familySource(model: FamilyFields): { hint: MessageKey; certain: boolean } | null {
  if (!model.family) return model.family_source === "not_applicable" ? { hint: "modelFamilyNotApplicableHint", certain: false } : null;
  if (model.family_source === "filename") return { hint: "modelFamilySourceFilename", certain: false };
  if (model.family_source === "weights") return { hint: "modelFamilySourceWeights", certain: true };
  if (model.family_source === "civitai") return { hint: "modelFamilySourceCivitai", certain: true };
  return { hint: "modelFamilySourceMetadata", certain: true };
}

/** 两个特殊项排最后:先「认不出」,再「不适用」。 */
const familyRank = (value: string) => (value === UNKNOWN_FAMILY ? 1 : value === NOT_APPLICABLE_FAMILY ? 2 : 0);

/** 这一批文件里有哪几种底模、各几个:多的在前,认不出的、不适用的排最后。 */
export function familyCounts(models: readonly ModelFile[]): [string, number][] {
  const counts = new Map<string, number>();
  for (const model of models) counts.set(familyOf(model), (counts.get(familyOf(model)) ?? 0) + 1);
  return [...counts.entries()].sort(
    (a, b) => familyRank(a[0]) - familyRank(b[0]) || b[1] - a[1] || a[0].localeCompare(b[0]),
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

/** 一张能选这个文件的工作流:哪一格(参数键)、那一格里它的原值、是不是已经在用它。 */
export type GenerationTarget = {
  option: GenerationOption;
  name: string;
  key: string;
  value: string;
  uses: boolean;
};

/** 生成选项给人看的名字里,连接名那一截去掉(「ComfyUI · 192.168.3.15 · portrait」→「portrait」)。 */
function workflowName(option: GenerationOption): string {
  const prefix = option.profile_name ? `${option.profile_name} · ` : "";
  return prefix && option.label.startsWith(prefix) ? option.label.slice(prefix.length) : option.label;
}

/**
 * 「用它生成」能交给哪几张工作流:**这个连接**上、有一格选的是这个文件所在目录(`x-model-folder`)、并且可选值里有它
 * 的生成选项。已经在用它的(模型库报的 used_by)排前面,其余按名字。路径分隔符不同(Windows 上的反斜杠)也认。
 */
export function generationTargets(options: readonly GenerationOption[], instanceId: string, model: ModelFile): GenerationTarget[] {
  const wanted = normModelName(model.name);
  const usedBy = new Set((model.used_by ?? []).map((flow) => flow.id));
  const out: GenerationTarget[] = [];
  for (const option of options) {
    if (option.plugin_instance_id !== instanceId) continue;
    for (const parameter of declaredParameters(option)) {
      if (parameter.modelFolder !== model.folder) continue;
      const value = parameter.options.find((one) => normModelName(one) === wanted);
      if (value === undefined) continue;
      out.push({ option, name: workflowName(option), key: parameter.key, value, uses: usedBy.has(option.model) });
      break;
    }
  }
  return out.sort((a, b) => Number(b.uses) - Number(a.uses) || a.name.localeCompare(b.name));
}
