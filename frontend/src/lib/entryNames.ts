/**
 * 一个生成模型、一个插件工具给人看的**两层名字**(ADR 0045:表单是工作流的入口)。
 *
 * ComfyUI 的一张工作流有一个「完整工作流」入口和它上面每张表单各一个入口,各是一个模型、一个工具。名字不拼成一句
 * (「工作流名 · 表单名」太长,文件名常常没法看,拼进去之后搜索、排序、分组都只能拆字符串):
 *
 * - **主名**是这一项自己的:表单入口是表单标题,完整工作流是工作流名,别的模型是显示名(`model_label`);
 * - **副名**说它从哪来:表单入口「来自 krea2-text-2-image」,有表单的完整工作流「完整工作流」,再接连接名
 *   (`profile_name`,「ComfyUI · http://…」,用户能改)。没有表单的工作流、别的模型只写连接名 —— 和以前一样。
 *
 * 后端只给结构化的几格(`model_label`、`group`、`profile_name`),怎么摆在这里一处定。插件节点、画板能力按插件聚合、不分
 * 连接,它们的副名没有连接名(`entryOrigin`)。
 */
import type { FieldOption } from "@/api/domains/workflows";
import type { components } from "@/api/generated/schema";
import type { MessageKey } from "@/app/messages";
import type { OptionSection } from "@/components/ui/searchable-select";

export type EntryGroup = components["schemas"]["EntryGroupOut"];
type Translate = (key: MessageKey) => string;

/** 两层名字。`secondary` 可以是空串(没什么可说的)。 */
export type TwoLayerName = { primary: string; secondary: string };

/** 有表单入口的那几组(工作流):它们的完整工作流副名写「完整工作流」,和表单分得开。 */
export function formedGroups(items: Iterable<{ group?: EntryGroup | null }>): Set<string> {
  const formed = new Set<string>();
  for (const item of items) {
    if (item.group?.entry === "form") formed.add(item.group.id);
  }
  return formed;
}

/** 副名里「这是哪个入口」那一截:表单入口「来自 X」,有表单的完整工作流「完整工作流」,别的没有(空串)。 */
export function entryOrigin(group: EntryGroup | null | undefined, formed: ReadonlySet<string>, t: Translate): string {
  if (!group) return "";
  if (group.entry === "form") return t("entryFromGroup").replace("{name}", group.label);
  return formed.has(group.id) ? t("entryFullWorkflow") : "";
}

type NamedOption = { model: string; model_label: string; profile_name: string; group?: EntryGroup | null;
                     provider_profile_id?: string };

/** 一个生成选项的两层名字:主名是 `model_label`,副名是入口那一截再接连接名。 */
export function generationOptionNames(option: NamedOption, formed: ReadonlySet<string>, t: Translate): TwoLayerName {
  const origin = entryOrigin(option.group, formed, t);
  return {
    primary: option.model_label || option.model,
    secondary: [origin, option.profile_name].filter(Boolean).join(" · "),
  };
}

/** 搜得到它的那几个词:主名、工作流名、模型 id(ComfyUI 是文件路径)、连接名 —— 搜「krea2」两个入口都在,搜表单标题只剩表单。 */
export function generationOptionKeywords(option: NamedOption): string[] {
  return [option.model_label, option.group?.label ?? "", option.model, option.profile_name].filter(Boolean);
}

/** 下拉里的一行(生成选项):名字、第二行、搜索词,有表单的工作流再带上它那一小组(只管搜索,见 SearchableSelect)。 */
export type PickerEntry = {
  label: string;
  description?: string;
  keywords: string[];
  section?: OptionSection;
};

/** 有表单的工作流的几个入口同属一小组:同一个连接上的同一张工作流。 */
function sectionOf(group: EntryGroup | null | undefined, formed: ReadonlySet<string>, connection: string): OptionSection | undefined {
  return group && formed.has(group.id) ? { key: `${connection}\n${group.id}` } : undefined;
}

/**
 * 一个生成选项在下拉里怎么摆(ADR 0045 §7「列表按工作流分组」):**每个入口一行、各自能选**,主名 + 第二行副名 ——
 * 完整工作流「krea2-text-2-image / 完整工作流 · 连接名」,表单「快速出图 / 来自 krea2-text-2-image · 连接名」,和别的模型
 * 左边对齐。同一张工作流的几个入口挨着(后端排好的顺序),搜到其中一个整组留着(`section`)。此前有表单的工作流上面是一行
 * 点不了的工作流名、下面「完整工作流」和表单缩进一格。
 */
export function generationPickerEntry(option: NamedOption, formed: ReadonlySet<string>, t: Translate): PickerEntry {
  const names = generationOptionNames(option, formed, t);
  const section = sectionOf(option.group, formed, option.provider_profile_id ?? option.profile_name);
  return { label: names.primary, description: names.secondary || undefined, keywords: generationOptionKeywords(option),
           ...(section ? { section } : {}) };
}

/** 一个用不了的记着的模型(见 lib/generationOptions 的 useMissingModel):和生成选项同几格名字,外加修法是不是升级。 */
type MissingNamed = NamedOption & { upgrade?: boolean };

/**
 * 一个用不了的记着的模型的两层名字(ADR 0045 修订之一):和生成选项一样摆 —— 主名「krea2-text-2-image 的表单」,副名「来自
 * krea2-text-2-image · 连接名」。还没问到时写「之前选的模型」:**不露 `plugin:…`、`#app` 这种编号**。
 */
export function missingModelNames(missing: MissingNamed | null, t: Translate): TwoLayerName {
  if (!missing) return { primary: t("genModelMissingName"), secondary: "" };
  return generationOptionNames(missing, new Set(), t);
}

/** 只有一行的地方(模型下拉的触发器、输入框底下那枚按钮):主名后面接「· 需要升级」/「· 用不了」。 */
export function missingModelLabel(missing: MissingNamed | null, t: Translate): string {
  return `${missingModelNames(missing, t).primary} · ${t(missing?.upgrade ? "genModelNeedsUpgrade" : "genModelUnusable")}`;
}

/** 只有一行、又放不下第二行说明的地方(原生 `title`、一句话的悬停):两层连成一句,中间用破折号隔开。 */
export function twoLayerTitle(name: TwoLayerName): string {
  return name.secondary ? `${name.primary} — ${name.secondary}` : name.primary;
}

/**
 * 现查选项里按生成选项列的那几项,摆成两层:第二行是入口那一截再接连接名,按工作流名、模型 id、连接名也搜得到;有表单的
 * 工作流的几个入口同属一小组(只管搜索,不画小标题、不缩进,见 generationPickerEntry)。后端只给结构化的几格
 * (workflows.field_options.generation_option_names),不拼成一句。别的选项原样。
 */
export function entryNamedOptions<T extends FieldOption>(options: readonly T[], t: Translate) {
  const formed = formedGroups(options.map((one) => ({ group: one.entry_group })));
  return options.map((one) => {
    if (one.profile_name === undefined) return one;
    const group = one.entry_group;
    const section = sectionOf(group, formed, one.profile_name);
    return {
      ...one,
      description: [entryOrigin(group, formed, t), one.profile_name].filter(Boolean).join(" · "),
      keywords: [group?.label ?? "", one.model ?? "", one.profile_name].filter(Boolean),
      ...(section ? { section } : {}),
    };
  });
}
