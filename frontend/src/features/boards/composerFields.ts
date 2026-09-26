import type { BoardItem } from "@/api/client";
import { nodeConfigTiers, type ConfigSpec } from "@/features/nodeForms/NodeConfigForm";
import { fieldDataType } from "@/features/nodeForms/fieldTypes";

/**
 * 节点产出者的面板(一格的能力、空格子上的生成器)把字段分到哪一块。**只看字段声明,不认识任何具体节点** ——
 * `board_sources` / `options` / `options_from` / `allow_custom` / `required` / `advanced` / `active_when`
 * (棘轮 nodeInspectorIsNodeAgnostic)。
 *
 *  · **宿主字段不出现**:一项能力吃的是它挂着的那一格的内容(后端 `host_fields`),那个字段不是一枚芯片、
 *    不是一段正文、不是一个参数 —— 它**就是**宿主;
 *  · **上游芯片**:别的能接上游的字段(`board_sources`),有得接或已经接上的,各一组;
 *  · **正文**:第一段自由的字(出图的提示词),没接上游的;
 *  · **底栏芯片**:挑一个的字段(固定选项、现查的清单),必填的在前,至多三枚;
 *  · 其余进「参数」。
 */

/** 产出者清单里一个字段的声明:节点表单那一份 + 画板多给的一样 —— 它能接哪几种上游格子。 */
export type BoardFieldSpec = ConfigSpec & { board_sources?: string[]; editor?: string };

type Field = [string, BoardFieldSpec];

/** 底栏里至多摆几枚设置芯片;其余的进「参数」。 */
export const BAR_CHIP_LIMIT = 3;

/** 能接上游的格子(便签、文档、图片 …… 3D 场景)—— 后端说的(`board_sources`)。 */
export function bindable(spec: BoardFieldSpec | undefined): boolean {
  return Boolean(spec?.board_sources?.length);
}

/** 这个字段收一串还是一份:文字字段(多张便签按连线顺序拼起来)和复数的素材字段收一串。 */
export function takesMany(key: string, spec: BoardFieldSpec): boolean {
  return Boolean(spec.board_sources?.includes("note")) || /(^|_)asset_ids$/.test(key);
}

/** 挑一个的字段:声明了固定选项,或者选项要现查(`options_from`)。清单之外还能手填的(`allow_custom`)不算 ——
 *  芯片只能挑,那种字段进「参数」,在那里能手填。 */
export function picksOne(spec: BoardFieldSpec | undefined): boolean {
  return Boolean((spec?.options?.length || spec?.options_from) && !spec?.allow_custom);
}

/** 一段自由的字(出图的提示词):面板的正文就是它。挑一个的、素材、专用控件都不算。 */
export function freeText(spec: BoardFieldSpec | undefined): boolean {
  return (
    (spec?.type === "text" || spec?.type === "template") &&
    !spec.options?.length &&
    !spec.options_from &&
    !spec.editor &&
    fieldDataType(spec) !== "asset"
  );
}

export function filled(value: unknown): boolean {
  return typeof value === "number" || typeof value === "boolean" || (typeof value === "string" && value.trim() !== "");
}

export interface ComposerFields {
  /** 能接上游、有得接或已经接上的字段:各一组上游芯片。 */
  upstream: Field[];
  /** 正文那一段自由的字;没有就是 undefined。 */
  body: Field | undefined;
  /** 底栏的设置芯片(挑一个的,必填在前)。 */
  chips: Field[];
  /** 进「参数」的:常用的在前、不常用的在后。 */
  rest: Field[];
  /** 「参数」里有必填还空着:按钮上一个点 —— 不点开就看不见的必填,不能让它安静地缺着。 */
  attention: boolean;
  /** 此刻参与的全部字段(`active_when`),宿主字段除外。 */
  active: Field[];
}

/**
 * 把字段分到面板的几块。`hostField`:宿主的内容填进的那个字段(一项能力),它哪一块都不进;
 * `fits(key)`:这个字段此刻有几格上游接得上(没有、也没接上的,不给一组空芯片)。
 */
export function composerFields({
  specs,
  config,
  bindings,
  hostField,
  fits,
}: {
  specs: Record<string, BoardFieldSpec>;
  config: Record<string, unknown>;
  bindings: Record<string, { from: string }[]>;
  hostField?: string | null;
  fits: (key: string) => BoardItem[];
}): ComposerFields {
  const isBound = (key: string) => Boolean(bindings[key]?.length);
  const notHost = ([key]: Field) => key !== hostField;
  const tiers = nodeConfigTiers(specs, config);
  const basic = (tiers.basic as Field[]).filter(notHost);
  const advanced = (tiers.advanced as Field[]).filter(notHost);
  const active = [...basic, ...advanced];
  const upstream = active.filter(([key, spec]) => bindable(spec) && (fits(key).length > 0 || isBound(key)));
  const body = basic.find(([key, spec]) => freeText(spec) && !isBound(key));
  const chips = basic
    .filter(([key, spec]) => picksOne(spec) && !isBound(key) && key !== body?.[0])
    .sort(([, a], [, b]) => Number(Boolean(b.required)) - Number(Boolean(a.required)))
    .slice(0, BAR_CHIP_LIMIT);
  const placed = new Set([body?.[0], ...chips.map(([key]) => key)]);
  const rest = active.filter(([key]) => !placed.has(key) && !isBound(key));
  const attention = rest.some(([key, spec]) => spec.required && !filled(config[key]) && !filled(spec.default));
  return { upstream, body, chips, rest, attention, active };
}

/**
 * 还差哪几样必填:没接上游、没填、没有缺省,也不是「清单只有一项就用它」的那种(`soleDefault`)。
 * 发送键据此是灰的,悬停说差哪几样(`boardToolMissing`)—— 不是点了才从服务端回一句错。
 */
export function missingFields(
  fields: ComposerFields,
  config: Record<string, unknown>,
  bindings: Record<string, { from: string }[]>,
  soleDefault: (key: string, spec: BoardFieldSpec) => boolean,
): Field[] {
  return fields.active.filter(
    ([key, spec]) =>
      spec.required && !bindings[key]?.length && !filled(config[key]) && !filled(spec.default) && !soleDefault(key, spec),
  );
}
